"""Start the Silo Optimiser app locally:  python tools/run_app.py [--port 8000] [--store PATH]

Opens nothing by itself; browse to http://127.0.0.1:8000/ . Saved silos go to the store folder (default
~/.silo-optimiser/store, outside the repository). Needs the optional api dependencies (fastapi, uvicorn).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import runpy  # noqa: E402

runpy.run_module("silo_engine.api", run_name="__main__", alter_sys=True)
