"""In-memory AsyncSession stand-in for the authoring services (no PostgreSQL).

It evaluates the simple SQLAlchemy statements the services issue (equality/IN/IS NULL/ILIKE
filters, ORDER BY, LIMIT, Question+QuestionRevision joins) against Python objects, emulates the
three SQL functions (``edu.question_key``, ``edu.workspace_staff_count``,
``edu.workspace_staff_role``) and records every statement so tests can assert, for example,
that a student export never references the key function. Keys inserted through the Core
``INSERT`` are kept in ``keys`` only, mirroring the INSERT-only grant on ``question_keys``.
"""

import re
from collections import defaultdict
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy.sql import operators
from sqlalchemy.sql.dml import Delete, Insert
from sqlalchemy.sql.elements import (
    BinaryExpression,
    BindParameter,
    BooleanClauseList,
    Grouping,
    Null,
    UnaryExpression,
)
from sqlalchemy.sql.schema import Column

from app.infrastructure.database import Base
from app.models.authoring import Question, QuestionRevision
from app.models.knowledge import CurriculumUnit


class Rows(list):
    def all(self):
        return list(self)

    def first(self):
        return self[0] if self else None


def _value(expr, env):
    if isinstance(expr, Grouping):
        return _value(expr.element, env)
    if isinstance(expr, Column):
        obj = env.get(expr.table.name)
        if obj is None:
            raise LookupError(expr.table.name)
        return getattr(obj, expr.key)
    if isinstance(expr, BindParameter):
        return expr.effective_value
    if isinstance(expr, Null):
        return None
    if isinstance(expr, BooleanClauseList | BinaryExpression):
        return _matches(expr, env)
    raise NotImplementedError(type(expr))


def _like(value, pattern):
    """SQL ILIKE with backslash escapes, as produced by ``question_bank.escape_like``."""
    out, i = [], 0
    while i < len(pattern):
        char = pattern[i]
        if char == "\\" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if char == "%" else "." if char == "_" else re.escape(char))
        i += 1
    return value is not None and re.fullmatch("".join(out), value, re.IGNORECASE | re.DOTALL)


def _matches(clause, env) -> bool:
    if clause is None:
        return True
    if isinstance(clause, Grouping):
        return _matches(clause.element, env)
    if isinstance(clause, BooleanClauseList):
        results = [_matches(c, env) for c in clause.clauses]
        return all(results) if clause.operator is operators.and_ else any(results)
    assert isinstance(clause, BinaryExpression), type(clause)
    try:
        left = _value(clause.left, env)
    except LookupError:
        return True  # filter on a table not present in this row (e.g. outer join)
    right = _value(clause.right, env)
    op = clause.operator
    if op is operators.eq:
        return left == right
    if op is operators.ne:
        return left != right
    if op is operators.lt:
        return left < right
    if op is operators.gt:
        return left > right
    if op is operators.in_op:
        return left in right
    if op is operators.is_:
        return left is right
    if op is operators.is_not:
        return left is not right
    if op is operators.ilike_op:
        return bool(_like(left, right))
    raise NotImplementedError(op)


def _sort(rows, stmt, key_env):
    for clause in reversed(list(stmt._order_by_clauses)):
        descending = isinstance(clause, UnaryExpression) and clause.modifier is operators.desc_op
        column = clause.element if isinstance(clause, UnaryExpression) else clause
        rows.sort(key=lambda row, c=column: _value(c, key_env(row)), reverse=descending)
    return rows


class FakeSession:
    def __init__(self):
        self.store: dict[type, list] = defaultdict(list)
        self.keys: dict[UUID, str] = {}
        self.statements: list = []
        self.staff_count = 2
        self.staff_roles: dict[UUID, str] = {}
        self.key_reads = 0
        self.flushes = 0

    @asynccontextmanager
    async def begin(self):
        yield

    def add(self, obj):
        bucket = self.store[type(obj)]
        if obj not in bucket:
            bucket.append(obj)

    def all(self, model):
        return list(self.store[model])

    async def flush(self):
        self.flushes += 1

    # -- statements -----------------------------------------------------------------------

    def _function(self, stmt):
        sql = str(stmt)
        params = list(stmt.compile().params.values())
        if "edu.question_key" in sql and "FROM edu.questions" not in sql:
            self.key_reads += 1
            return True, self.keys.get(params[0])
        if "edu.workspace_staff_count" in sql:
            return True, self.staff_count
        if "edu.workspace_staff_role" in sql:
            return True, self.staff_roles.get(params[1])
        return False, None

    def _select(self, stmt):
        descriptions = stmt.column_descriptions
        entities = [d["entity"] for d in descriptions]
        if entities[:2] == [Question, QuestionRevision]:
            return self._question_join(stmt, descriptions)
        model = entities[0]
        rows = [
            obj
            for obj in self.store[model]
            if _matches(stmt.whereclause, {model.__table__.name: obj})
        ]
        rows = _sort(rows, stmt, lambda obj: {model.__table__.name: obj})
        limit = stmt._limit
        rows = rows[:limit] if limit is not None else rows
        if descriptions[0]["expr"] is model:
            return rows
        columns = [d["expr"].key for d in descriptions]
        if len(columns) == 1:
            return [getattr(obj, columns[0]) for obj in rows]
        return [tuple(getattr(obj, c) for c in columns) for obj in rows]

    def _question_join(self, stmt, descriptions):
        out = []
        for question in self.store[Question]:
            revision = next(
                (r for r in self.store[QuestionRevision] if r.id == question.current_revision_id),
                None,
            )
            unit = next(
                (u for u in self.store[CurriculumUnit] if u.id == question.curriculum_unit_id),
                None,
            )
            env = {"questions": question, "question_revisions": revision}
            if revision is None or not _matches(stmt.whereclause, env):
                continue
            row = [question, revision]
            for description in descriptions[2:]:
                if description["name"] == "unit_code":
                    row.append(unit.unit_code if unit else None)
                else:  # edu.question_key(question_revisions.id) AS correct_key
                    row.append(self.keys.get(revision.id))
            out.append(tuple(row))
        out = _sort(out, stmt, lambda row: {"questions": row[0], "question_revisions": row[1]})
        return out[: stmt._limit] if stmt._limit is not None else out

    async def scalar(self, stmt, params=None):
        self.statements.append(stmt)
        handled, value = self._function(stmt)
        if handled:
            return value
        rows = self._select(stmt)
        return rows[0] if rows else None

    async def scalars(self, stmt, params=None):
        self.statements.append(stmt)
        return Rows(self._select(stmt))

    async def execute(self, stmt, params=None):
        self.statements.append(stmt)
        if isinstance(stmt, Insert):
            values = stmt.compile().params
            assert stmt.table.name == "question_keys", stmt.table.name
            revision = values["question_revision_id"]
            assert revision not in self.keys, "keys are immutable per revision"
            self.keys[revision] = values["correct_key"]
            return Rows()
        if isinstance(stmt, Delete):
            model = next(
                m.class_ for m in Base.registry.mappers if m.local_table.name == stmt.table.name
            )
            keep = [
                obj
                for obj in self.store[model]
                if not _matches(stmt.whereclause, {stmt.table.name: obj})
            ]
            self.store[model] = keep
            return Rows()
        if "set_config" in str(stmt):
            return Rows()
        return Rows(self._select(stmt))


def scope(workspace_id: UUID | None = None, user_id: UUID | None = None, role: str = "teacher"):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id or uuid4()),
        workspace=SimpleNamespace(id=workspace_id or uuid4()),
        role=role,
    )
