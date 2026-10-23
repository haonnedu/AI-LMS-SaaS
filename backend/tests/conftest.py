"""Windows psycopg async requires the Selector event loop, as in run_api.py."""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
