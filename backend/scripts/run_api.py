"""Local API launcher with Psycopg-compatible Windows event loop."""

import asyncio
import sys

import uvicorn


def main() -> None:
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=8000, access_log=False)
    server = uvicorn.Server(config)
    # Uvicorn's Windows run() selects Proactor explicitly, overriding loop policy.
    # Own the runner so Psycopg always receives its supported Selector loop.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(server.serve())


if __name__ == "__main__":
    main()
