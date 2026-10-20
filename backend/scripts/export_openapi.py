"""Export the reviewed contract without connecting to infrastructure."""

import argparse
import json
from pathlib import Path

from app.core.config import Settings
from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "output", type=Path, help="Output JSON path, e.g. ../contracts/openapi.json"
    )
    args = parser.parse_args()
    # A fixed test configuration makes the contract independent of developer .env files.
    application = create_app(Settings(_env_file=None, environment="test"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(application.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Exported OpenAPI to {args.output}")


if __name__ == "__main__":
    main()
