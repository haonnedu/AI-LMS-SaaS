"""Bootstrap fresh/empty-0001 adoption on a disposable PostgreSQL database only."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

ADMIN_URL = os.getenv("AUTH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="Disposable PostgreSQL required")


@pytest.fixture
def bootstrap_database():
    assert ADMIN_URL and ADMIN_URL.rsplit("/", 1)[-1].endswith("_test")
    engine = create_engine(ADMIN_URL)
    suffix = uuid4().hex[:10]
    names = {
        name: name + "_" + suffix
        for name in ("eduvia_migrator", "eduvia_runtime", "eduvia_identity_owner")
    }
    with engine.begin() as db:
        db.execute(text("DROP SCHEMA IF EXISTS edu CASCADE"))
        db.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
    source = (Path(__file__).parents[2] / "deploy/postgres/bootstrap.sql").read_text()
    source = "\n".join(line for line in source.splitlines() if not line.startswith("\\"))
    source = source.replace("BEGIN;", "", 1).replace("COMMIT;", "", 1)
    source = source.replace(":'migrator_password'", "'bootstrap_test_only'")
    source = source.replace(":'runtime_password'", "'bootstrap_runtime_test_only'")
    source = source.replace(
        ':"database_name"', engine.dialect.identifier_preparer.quote(engine.url.database)
    )
    for original, replacement in names.items():
        source = source.replace(original, replacement)
    yield engine, source, names
    with engine.begin() as db:
        db.execute(text("DROP SCHEMA IF EXISTS edu CASCADE"))
        db.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
        for name in names.values():
            if db.scalar(
                text("SELECT EXISTS(SELECT FROM pg_roles WHERE rolname=:name)"), {"name": name}
            ):
                db.execute(text(f'DROP OWNED BY "{name}"'))
                db.execute(text(f'DROP ROLE "{name}"'))
    engine.dispose()


@pytest.mark.parametrize("legacy", [False, True])
def test_fresh_and_empty_0001_adoption(bootstrap_database, legacy):
    engine, source, names = bootstrap_database
    if legacy:
        with engine.begin() as db:
            db.execute(text("CREATE SCHEMA edu"))
            db.execute(
                text("CREATE TABLE public.alembic_version(version_num varchar(32) PRIMARY KEY)")
            )
            db.execute(text("INSERT INTO public.alembic_version VALUES('0001_bootstrap')"))
    with engine.begin() as db:
        db.execute(text(source))
    with engine.connect() as db:
        owner = db.scalar(
            text("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='edu'")
        )
        assert owner == names["eduvia_migrator"]
        if legacy:
            assert (
                db.scalar(text("SELECT version_num FROM public.alembic_version"))
                == "0001_bootstrap"
            )
            version_owner = db.scalar(
                text(
                    "SELECT pg_get_userbyid(relowner) FROM pg_class "
                    "WHERE oid='public.alembic_version'::regclass"
                )
            )
            assert version_owner == names["eduvia_migrator"]


@pytest.mark.parametrize("baseline", ["populated", "wrong_revision"])
def test_reject_unsafe_adoption_without_mutation(bootstrap_database, baseline):
    engine, source, names = bootstrap_database
    with engine.begin() as db:
        db.execute(text("CREATE SCHEMA edu"))
        if baseline == "populated":
            db.execute(text("CREATE TABLE edu.keep_me(value text)"))
            db.execute(text("INSERT INTO edu.keep_me VALUES('preserved')"))
        else:
            db.execute(
                text("CREATE TABLE public.alembic_version(version_num varchar(32) PRIMARY KEY)")
            )
            db.execute(
                text("INSERT INTO public.alembic_version VALUES('0002_identity_and_workspaces')")
            )
    with pytest.raises(DBAPIError):
        with engine.begin() as db:
            db.execute(text(source))
    with engine.connect() as db:
        assert not db.scalar(
            text("SELECT EXISTS(SELECT FROM pg_roles WHERE rolname=:name)"),
            {"name": names["eduvia_migrator"]},
        )
        if baseline == "populated":
            assert db.scalar(text("SELECT value FROM edu.keep_me")) == "preserved"
        else:
            assert (
                db.scalar(text("SELECT version_num FROM public.alembic_version"))
                == "0002_identity_and_workspaces"
            )
