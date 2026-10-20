import asyncio
import importlib.util
import sys
from pathlib import Path


def test_native_runner_uses_psycopg_compatible_loop(monkeypatch):
    path = Path(__file__).parents[1] / "scripts" / "run_api.py"
    spec = importlib.util.spec_from_file_location("run_api", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    observed = []

    class ServerStub:
        def __init__(self, config):
            self.config = config

        async def serve(self):
            loop = asyncio.get_running_loop()
            observed.append(loop)
            if sys.platform == "win32":
                assert isinstance(loop, asyncio.SelectorEventLoop)

    monkeypatch.setattr(module.uvicorn, "Server", ServerStub)
    module.main()
    assert len(observed) == 1
    assert observed[0].is_closed()
