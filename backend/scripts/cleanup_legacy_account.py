"""Delete one explicitly identified test account. Operator URL only; dry-run by default."""

import argparse
import json
import os
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import create_engine, text


def cleanup(connection, issuer, subject, user_id, apply=False):
    parsed = urlsplit(issuer)
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".auth0.com"):
        raise ValueError("Only an explicit retired Auth0 tenant issuer is supported")
    if not subject.startswith("auth0|"):
        raise ValueError("Only a retired Auth0 database identity is supported")
    # Table locks prevent new memberships/identities changing the reviewed scope mid-delete.
    tables = ["users", "workspaces", "workspace_members", "user_identities"]
    receipts = connection.scalar(text("SELECT to_regclass('edu.identity_transfers') IS NOT NULL"))
    if receipts:
        tables.append("identity_transfers")
    connection.execute(
        text("LOCK TABLE " + ",".join("edu." + t for t in tables) + " IN SHARE ROW EXCLUSIVE MODE")
    )
    row = connection.execute(
        text("SELECT provider_issuer,provider_sub FROM edu.users WHERE id=:id"), {"id": user_id}
    ).first()
    if row is None:
        return {"status": "already_absent", "userId": str(user_id)}
    if tuple(row) != (issuer, subject):
        raise ValueError("Canonical issuer/subject/UUID do not match")
    identities = connection.execute(
        text("SELECT issuer,subject FROM edu.user_identities WHERE user_id=:id"), {"id": user_id}
    ).all()
    if any(tuple(identity) != (issuer, subject) for identity in identities):
        raise ValueError("Additional identity exists; account cannot be discarded")
    # Refuse new dependent product tables instead of silently cascading product data.
    references = connection.execute(
        text("""SELECT ns.nspname,c.relname FROM pg_constraint fk
      JOIN pg_class c ON c.oid=fk.conrelid JOIN pg_namespace ns ON ns.oid=c.relnamespace
      WHERE fk.contype='f'
        AND fk.confrelid IN ('edu.users'::regclass,'edu.workspaces'::regclass)""")
    ).all()
    if any(schema != "edu" or table not in tables for schema, table in references):
        raise ValueError("Unreviewed dependent tables exist")
    workspaces = connection.execute(
        text("SELECT id,workspace_type FROM edu.workspaces WHERE personal_owner_user_id=:id"),
        {"id": user_id},
    ).all()
    if any(kind != "personal" for _, kind in workspaces):
        raise ValueError("Non-personal workspace exists")
    workspace_ids = [str(workspace) for workspace, _ in workspaces]
    memberships = connection.execute(
        text(
            "SELECT user_id,workspace_id FROM edu.workspace_members WHERE "
            "user_id=:id OR workspace_id IN "
            "(SELECT id FROM edu.workspaces WHERE personal_owner_user_id=:id)"
        ),
        {"id": user_id},
    ).all()
    if any(
        str(member) != str(user_id) or str(workspace) not in workspace_ids
        for member, workspace in memberships
    ):
        raise ValueError("Shared workspace or another member exists")
    if receipts and connection.scalar(
        text("SELECT count(*) FROM edu.identity_transfers WHERE user_id=:id"), {"id": user_id}
    ):
        raise ValueError("Account has transfer receipts; review migrated ownership separately")
    report = {
        "status": "deleted" if apply else "dry_run",
        "userId": str(user_id),
        "workspaceIds": workspace_ids,
        "memberships": len(memberships),
        "identities": len(identities),
    }
    if apply:
        params = {"id": user_id}
        connection.execute(text("DELETE FROM edu.workspace_members WHERE user_id=:id"), params)
        connection.execute(
            text("DELETE FROM edu.workspaces WHERE personal_owner_user_id=:id"), params
        )
        connection.execute(text("DELETE FROM edu.user_identities WHERE user_id=:id"), params)
        connection.execute(text("DELETE FROM edu.users WHERE id=:id"), params)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--user-id", required=True, type=UUID)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    url = os.environ.get("CLEANUP_DATABASE_URL")
    if not url:
        parser.error(
            "Set CLEANUP_DATABASE_URL to a DBA connection; never put it in command arguments"
        )
    engine = create_engine(url, hide_parameters=True, connect_args={"connect_timeout": 5})
    try:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL statement_timeout='15s'"))
            connection.execute(text("SET LOCAL lock_timeout='5s'"))
            print(
                json.dumps(cleanup(connection, args.issuer, args.subject, args.user_id, args.apply))
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
