"""HTTP API for the silo builder (docs/PLATFORM_GAP_ANALYSIS.md step 8, gap G10). A thin layer: it validates, stores
and runs configurations through the engine, config, store and experiments packages, and holds no simulation logic.

    python -m silo_engine.api            serve on http://127.0.0.1:8000 (local only; docs at /docs)

Endpoints:
    GET  /health
    POST /validate                                   pre-run report for a configuration (422 if unreadable)
    GET  /sites ; POST /sites {config, note}          list; save a new version
    GET  /sites/{id}[?version=n] ; /history ; /diff?a=&b=
    GET  /sites/{id}/scenarios ; POST {name, base_version, ops, note} ; GET /sites/{id}/scenarios/{name}
    POST /runs {site_id, version | scenario, replications, base_seed, days, demand_factor, policy} -> 202 run_id
    GET  /runs/{id} ; GET /runs/{id}/results
    GET  /meta                                       equipment catalogue (types, fields, allowed connections)
    GET  /examples ; GET /examples/{file}            synthetic example sites (evidence/configs; labelled synthetic)
    GET  /app/                                       the silo builder (static files in api/static; no build step)

A run uses an immutable snapshot of the configuration it was started with; its results carry the engine version,
configuration hash, seeds, replications and assumptions (experiments.runner metadata). A configuration whose pre-run
report has errors is refused (409). Runs are kept in memory for the life of the server (a known limitation for now).
Requires the optional `api` dependencies (fastapi, uvicorn).
"""
import copy
import dataclasses
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import VERSION
from ..config import ConfigSchemaError, load_site_config
from ..config.catalogue import catalogue
from ..config.report import prerun_report
from ..config.schema import config_hash
from ..experiments.runner import run_experiment
from ..store import ConfigStore, StoreError, StoreNotFound, diff_configs


STATIC = Path(__file__).parent / "static"
EXAMPLES = Path(__file__).resolve().parents[3] / "evidence" / "configs"  # synthetic sites in the repository


class SaveRequest(BaseModel):
    config: dict[str, Any]
    note: str = ""


class ScenarioRequest(BaseModel):
    name: str
    base_version: int
    ops: list[dict[str, Any]]
    note: str = ""


class RunRequest(BaseModel):
    site_id: str
    version: int | None = None  # default: latest
    scenario: str | None = None  # a stored scenario (its base version is used)
    replications: int = Field(default=10, ge=1, le=500)
    base_seed: int = 20261019
    days: int = Field(default=1, ge=1, le=60)
    demand_factor: float = Field(default=1.0, gt=0)
    policy: str | None = None


def _store_errors(fn):
    try:
        return fn()
    except StoreNotFound as e:
        raise HTTPException(404, str(e)) from None
    except StoreError as e:
        raise HTTPException(400, str(e)) from None
    except ConfigSchemaError as e:
        raise HTTPException(422, {"message": "The configuration could not be read.", "messages": e.problems}) from None


def _interval(i) -> dict:
    return {"n": i.n, "mean": i.mean, "sd": i.sd, "half_width": i.half_width, "low": i.low, "high": i.high}


def create_app(store_root: Path | str | None = None) -> FastAPI:
    store = ConfigStore(store_root)
    app = FastAPI(title="Silo Optimiser API", version=VERSION)
    runs: dict[str, dict] = {}
    lock = threading.Lock()
    pool = ThreadPoolExecutor(max_workers=1)

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/app/")

    @app.get("/meta")
    def meta():
        return catalogue()

    def _examples() -> list[dict]:
        index = EXAMPLES / "index.json"
        if not index.exists():
            return []
        data = json.loads(index.read_text(encoding="utf-8"))
        return [{"file": c["file"], "label": c["label"], "note": f"Synthetic: {c['origin']}"}
                for c in data["configurations"] if c.get("synthetic")]

    @app.get("/examples")
    def examples():
        return _examples()

    @app.get("/examples/{file}")
    def example(file: str):
        if file not in {e["file"] for e in _examples()}:
            raise HTTPException(404, f"No example {file}.")
        return json.loads((EXAMPLES / file).read_text(encoding="utf-8"))

    @app.get("/health")
    def health():
        return {"status": "ok", "engine_version": VERSION}

    @app.post("/validate")
    def validate(config: dict[str, Any]):
        return _store_errors(lambda: prerun_report(load_site_config(copy.deepcopy(config))).as_dict())

    @app.get("/sites")
    def sites():
        return store.list_sites()

    @app.post("/sites")
    def save(req: SaveRequest):
        return _store_errors(lambda: dataclasses.asdict(store.save(req.config, note=req.note)))

    @app.get("/sites/{site_id}")
    def load(site_id: str, version: int | None = None):
        return _store_errors(lambda: store.load(site_id, version))

    @app.get("/sites/{site_id}/history")
    def history(site_id: str):
        return _store_errors(lambda: store.history(site_id))

    @app.get("/sites/{site_id}/diff")
    def diff(site_id: str, a: int, b: int):
        return _store_errors(lambda: diff_configs(store.load(site_id, a), store.load(site_id, b)))

    @app.get("/sites/{site_id}/scenarios")
    def scenarios(site_id: str):
        return _store_errors(lambda: store.list_scenarios(site_id))

    @app.post("/sites/{site_id}/scenarios")
    def save_scenario(site_id: str, req: ScenarioRequest):
        return _store_errors(lambda: store.save_scenario(site_id, req.name, req.base_version, req.ops, req.note))

    @app.get("/sites/{site_id}/scenarios/{name}")
    def load_scenario(site_id: str, name: str):
        return _store_errors(lambda: store.load_scenario(site_id, name))

    @app.post("/runs", status_code=202)
    def start_run(req: RunRequest):
        def snapshot():
            if req.scenario is not None:
                sc = store.load_scenario(req.site_id, req.scenario)
                return sc["config"], sc["base_version"]
            raw = store.load(req.site_id, req.version)
            return raw, raw["version"]
        raw, version = _store_errors(snapshot)
        site = _store_errors(lambda: load_site_config(copy.deepcopy(raw)))
        report = prerun_report(site).as_dict()
        if not report["ok"]:
            raise HTTPException(409, {"message": "The configuration has errors and cannot run.", "report": report})
        run_id = uuid.uuid4().hex[:12]
        record = {"run_id": run_id, "state": "queued", "site_id": req.site_id, "version": version,
                  "scenario": req.scenario, "config_hash": config_hash(site), "request": req.model_dump(),
                  "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "error": None}
        with lock:
            runs[run_id] = {"record": record, "results": None}

        def work():
            with lock:
                record["state"] = "running"
            try:
                exp = run_experiment(site, replications=req.replications, base_seed=req.base_seed, days=req.days,
                                     demand_factor=req.demand_factor, policy=req.policy)
                results = {"summary": {k: _interval(v) for k, v in exp.summary.items()},
                           "replications": [dataclasses.asdict(r) for r in exp.replications],
                           "failed": exp.failed, "metadata": exp.metadata}
                with lock:
                    runs[run_id]["results"], record["state"] = results, "done"
            except Exception as e:  # reported, never hidden
                with lock:
                    record["state"], record["error"] = "failed", f"{type(e).__name__}: {e}"
        pool.submit(work)
        return {"run_id": run_id, "state": record["state"]}

    def _run(run_id: str) -> dict:
        with lock:
            if run_id not in runs:
                raise HTTPException(404, f"No run {run_id}.")
            return runs[run_id]

    @app.get("/runs/{run_id}")
    def run_state(run_id: str):
        return dict(_run(run_id)["record"])

    @app.get("/runs/{run_id}/results")
    def run_results(run_id: str):
        r = _run(run_id)
        if r["results"] is None:
            raise HTTPException(409, f"Run {run_id} is {r['record']['state']}; no results yet.")
        return r["results"]

    app.mount("/app", StaticFiles(directory=STATIC, html=True), name="app")
    return app
