"""Operator-only counts. Never logs subjects, emails, tokens or database credentials."""

import argparse
import json

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    url = get_settings().database_url.get_secret_value()
    if make_url(url).username in {"eduvia_runtime", "eduvia_auth_runtime"}:
        raise SystemExit("Use the migration/operator role, not a runtime role")
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.connect() as db:
            row = db.execute(
                text("""SELECT count(*) AS total,
                  count(*) FILTER(WHERE EXISTS(SELECT 1 FROM edu.user_identities target
                    WHERE target.user_id=source.user_id AND target.issuer=:target)) AS migrated
                  FROM edu.user_identities source WHERE source.issuer=:source"""),
                {"source": args.source, "target": args.target},
            ).one()
            print(
                json.dumps(
                    {
                        "total": row.total,
                        "migrated": row.migrated,
                        "remaining": row.total - row.migrated,
                    }
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
