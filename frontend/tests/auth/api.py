import asyncio
import sys
import uvicorn

with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop if sys.platform=="win32" else None) as runner:
    runner.run(uvicorn.Server(uvicorn.Config("app.main:app",host="127.0.0.1",port=8005,access_log=False)).serve())
