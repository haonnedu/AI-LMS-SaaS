import asyncio
import uvicorn

with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
    runner.run(uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", port=8006, access_log=False)).serve())
