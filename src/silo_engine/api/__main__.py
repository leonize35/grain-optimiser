"""Serve the API locally: python -m silo_engine.api [--port 8000] [--store PATH]. Binds to 127.0.0.1 only."""
import argparse

import uvicorn

from . import create_app
from ..store import default_store_root

parser = argparse.ArgumentParser(description="Silo Optimiser API (local only)")
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--store", default=None, help=f"configuration store folder (default {default_store_root()})")
args = parser.parse_args()
uvicorn.run(create_app(args.store), host="127.0.0.1", port=args.port)
