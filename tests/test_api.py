"""HTTP API (docs/PLATFORM_GAP_ANALYSIS.md step 8, G10): validate, store, scenarios and runs, through an in-process
client. Each test uses its own temporary store; nothing is written inside the repository. Test inputs only."""
import copy
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from silo_engine import VERSION  # noqa: E402
from silo_engine.api import create_app  # noqa: E402
from test_outcomes_clearance import RAW  # noqa: E402
from test_unloading_labour import site as two_silo_site  # noqa: E402


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path))


def runnable():
    raw = two_silo_site(workers=2)
    del raw["unloading_labour"], raw["operator_pools"]
    raw["demand"] = {"unload": {"daily": 20, "payload": [30, 30, 30], "mix": {"YM": 1}}}
    for e in raw["equipment"]:
        if e["type"] == "bin":
            e["capT"] = 5000
    return raw


def test_health_reports_the_engine_version(client):
    assert client.get("/health").json() == {"status": "ok", "engine_version": VERSION}


def test_validate_returns_the_prerun_report(client):
    ok = client.post("/validate", json=RAW)
    assert ok.status_code == 200 and ok.json()["ok"] is True
    bad = copy.deepcopy(RAW)
    bad["edges"].append(["E1", "GHOST"])
    r = client.post("/validate", json=bad).json()
    assert r["ok"] is False and r["errors"] >= 1 and all("fix" in f for f in r["findings"])


def test_unreadable_configuration_is_a_422_with_messages(client):
    bad = copy.deepcopy(RAW)
    bad["equipment"][0]["capacity"] = 3
    r = client.post("/validate", json=bad)
    assert r.status_code == 422 and any("capacity" in m for m in r.json()["detail"]["messages"])


def test_save_load_history_and_diff(client):
    v1 = client.post("/sites", json={"config": RAW, "note": "first"}).json()
    changed = copy.deepcopy(RAW)
    changed["hours"]["overtime"] = 1
    v2 = client.post("/sites", json={"config": changed, "note": "longer overtime"}).json()
    assert (v1["version"], v2["version"]) == (1, 2) and v1["config_hash"] != v2["config_hash"]
    assert client.get("/sites").json() == ["clearance"]
    assert client.get("/sites/clearance").json()["hours"]["overtime"] == 1
    assert client.get("/sites/clearance", params={"version": 1}).json()["hours"]["overtime"] == 0.5
    assert [h["note"] for h in client.get("/sites/clearance/history").json()] == ["first", "longer overtime"]
    d = client.get("/sites/clearance/diff", params={"a": 1, "b": 2}).json()
    assert d == [{"kind": "changed", "where": "hours", "field": "overtime", "from": 0.5, "to": 1}]
    assert client.get("/sites/nowhere").status_code == 404


def test_scenarios_never_edit_the_base(client):
    client.post("/sites", json={"config": RAW, "note": "baseline"})
    r = client.post("/sites/clearance/scenarios", json={
        "name": "more_overtime", "base_version": 1, "ops": [{"op": "set", "path": "hours.overtime", "value": 2}]})
    assert r.status_code == 200
    assert client.get("/sites/clearance/scenarios").json() == ["more_overtime"]
    assert client.get("/sites/clearance/scenarios/more_overtime").json()["config"]["hours"]["overtime"] == 2
    assert client.get("/sites/clearance").json()["hours"]["overtime"] == 0.5
    bad = client.post("/sites/clearance/scenarios", json={
        "name": "broken", "base_version": 1, "ops": [{"op": "remove_equipment", "id": "GHOST"}]})
    assert bad.status_code == 400 and "GHOST" in bad.json()["detail"]


def wait(client, run_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(f"/runs/{run_id}").json()
        if r["state"] in ("done", "failed"):
            return r
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_a_run_records_its_snapshot_and_reproducibility_metadata(client):
    client.post("/sites", json={"config": runnable(), "note": "baseline"})
    start = client.post("/runs", json={"site_id": "two-silo", "version": 1, "replications": 2, "base_seed": 5})
    assert start.status_code == 202
    run = wait(client, start.json()["run_id"])
    assert run["state"] == "done" and run["config_hash"] == client.get("/sites/two-silo/history").json()[0]["config_hash"]
    res = client.get(f"/runs/{run['run_id']}/results").json()
    m = res["metadata"]
    assert (m["engine_version"], m["config_hash"], m["replications"], m["base_seed"]) == (VERSION, run["config_hash"], 2, 5)
    assert len(m["seeds"]) == 2 and "assumptions" in m and m["summary_scope"] == "all replications"
    assert res["summary"]["received_t"]["n"] == 2
    again = wait(client, client.post("/runs", json={"site_id": "two-silo", "version": 1, "replications": 2,
                                                    "base_seed": 5}).json()["run_id"])
    assert client.get(f"/runs/{again['run_id']}/results").json()["summary"] == res["summary"]  # reproducible


def test_a_run_of_a_scenario_uses_the_overlay(client):
    client.post("/sites", json={"config": runnable(), "note": "baseline"})
    client.post("/sites/two-silo/scenarios", json={"name": "double", "base_version": 1,
                                                    "ops": [{"op": "set", "path": "demand.unload.daily", "value": 40}]})
    base = wait(client, client.post("/runs", json={"site_id": "two-silo", "replications": 1, "base_seed": 5}).json()["run_id"])
    sc = wait(client, client.post("/runs", json={"site_id": "two-silo", "scenario": "double", "replications": 1,
                                                 "base_seed": 5}).json()["run_id"])
    assert sc["config_hash"] != base["config_hash"] and sc["scenario"] == "double"
    arrived = lambda r: client.get(f"/runs/{r['run_id']}/results").json()["replications"][0]["intended"]  # noqa: E731
    assert arrived(sc) > arrived(base)


def test_a_configuration_that_cannot_run_is_refused_with_its_report(client):
    draft = runnable()
    draft["edges"].append(["EA", "GHOST"])
    client.post("/sites", json={"config": draft, "note": "draft"})
    r = client.post("/runs", json={"site_id": "two-silo", "replications": 1})
    assert r.status_code == 409 and r.json()["detail"]["report"]["ok"] is False


def test_unknown_run_is_404(client):
    assert client.get("/runs/nope").status_code == 404
