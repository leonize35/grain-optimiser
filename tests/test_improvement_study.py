"""TLS slice T6 (docs/TLS_ANALYSIS_DESIGN.md §6, §8): an improvement study over replications, its storage, and the API.
Test inputs only (synthetic sites). Analysis only: the site configuration is never changed.

A study belongs to a site and holds the analysis settings beside (not inside) the configuration: step classes,
the CTQ and the TOC thresholds. They do not affect the simulation, so they are not in the configuration hash.
"""
import copy
import time

import pytest

from silo_engine.analysis.study import improvement_study
from silo_engine.config import load_site_config
from silo_engine.config.schema import config_hash
from silo_engine.store import ConfigStore, StoreError
from test_load_classes import site as small_site
from test_outcomes_clearance import RAW, run

STUDY = {"name": "baseline_review", "classification": {"tip": "value_adding", "weigh_in": "necessary",
                                                       "weigh_out": "necessary"},
         "ctq": {"measure": "turnaround", "usl": 10}, "settings": {"lead_share": 0.4, "lead_ratio": 1.5}}


def test_a_study_combines_toc_lean_and_six_sigma_over_replications():
    """Two identical runs of tests/test_outcomes_clearance.py: pooled values equal the single-run values."""
    s = load_site_config(copy.deepcopy(RAW))
    one, two = improvement_study(s, [run()], STUDY), improvement_study(s, [run(), run()], STUDY)
    assert one["toc"]["candidates"][0]["id"] == "H1" and one["toc"]["constraint"] == "H1"
    assert [(c["id"], c["truck_min"]) for c in two["toc"]["candidates"]] == [("H1", 3), ("WB_IN", 2)]
    assert two["toc"]["led_runs"] == {"H1": 2}  # the constraint in each run
    assert two["lean"]["process_cycle_efficiency"] == pytest.approx(5 / 12.75)
    assert two["lean"]["adds_up"] is True
    assert two["six_sigma"]["defect_share"] == 0.6 and two["six_sigma"]["replications"] == 2
    assert two["resource_use"]["H1"]["utilisation"] == pytest.approx(20 / 54)
    assert two["little"]["exact_ok"] is True
    assert two["reconciled"] is True


def test_a_study_without_a_ctq_or_classes_still_reports_toc():
    s = load_site_config(copy.deepcopy(RAW))
    r = improvement_study(s, [run()], {"name": "x"})
    assert r["six_sigma"] is None and r["lean"]["process_cycle_efficiency"] is None
    assert r["toc"]["constraint"] == "H1"
    assert "not validated" in r["assurance"]


def test_studies_are_stored_beside_the_configuration(tmp_path):
    store = ConfigStore(tmp_path)
    v = store.save(small_site(payload=[20, 25, 30]), note="base")
    before = config_hash(load_site_config(store.load(v.site_id, v.version)))
    store.save_study(v.site_id, STUDY)
    assert store.list_studies(v.site_id) == ["baseline_review"]
    assert store.load_study(v.site_id, "baseline_review")["ctq"] == {"measure": "turnaround", "usl": 10}
    assert config_hash(load_site_config(store.load(v.site_id, v.version))) == before
    with pytest.raises(StoreError, match="value_adding, necessary or waste"):
        store.save_study(v.site_id, {**STUDY, "classification": {"tip": "useful"}})
    with pytest.raises(StoreError, match="upper limit"):
        store.save_study(v.site_id, {**STUDY, "ctq": {"measure": "turnaround"}})


fastapi = pytest.importorskip("fastapi")


def test_api_runs_a_study_and_a_screening(tmp_path):
    from fastapi.testclient import TestClient
    from silo_engine.api import create_app
    c = TestClient(create_app(tmp_path))
    v = c.post("/sites", json={"config": small_site(payload=[20, 25, 30]), "note": "base"}).json()
    sid = v["site_id"]
    assert c.post(f"/sites/{sid}/studies", json=STUDY).status_code == 200
    assert c.get(f"/sites/{sid}/studies").json() == ["baseline_review"]
    st = c.post("/analyses", json={"site_id": sid, "version": v["version"], "study": "baseline_review",
                                   "replications": 2, "base_seed": 3}).json()

    def wait(path):
        for _ in range(600):
            rec = c.get(path).json()
            if rec["state"] in ("done", "failed"):
                return rec
            time.sleep(0.05)
        raise AssertionError("timed out")
    a = wait(f"/analyses/{st['analysis_id']}")
    assert a["state"] == "done", a.get("error")
    res = a["results"]
    assert {"toc", "lean", "six_sigma", "resource_use", "metadata"} <= set(res)
    assert res["metadata"]["replications"] == 2 and res["metadata"]["study"]["name"] == "baseline_review"
    assert res["metadata"]["config_hash"] == v["config_hash"]
    c.post(f"/sites/{sid}/scenarios", json={"name": "fast_tip", "base_version": v["version"],
                                            "ops": [{"op": "update_equipment", "id": "H1", "fields": {"tip": [5, 5, 5]}}]})
    sc = c.post("/screenings", json={"site_id": sid, "version": v["version"], "factors": ["fast_tip"],
                                     "responses": ["unload.mean_turnaround_min"], "replications": 2, "base_seed": 3}).json()
    sres = wait(f"/screenings/{sc['screening_id']}")
    assert sres["state"] == "done", sres.get("error")
    eff = sres["results"]["effects"]["unload.mean_turnaround_min"][0]
    assert eff["factor"] == "fast_tip" and eff["effect"] < 0
    assert c.post("/screenings", json={"site_id": sid, "version": v["version"], "factors": ["nope"],
                                       "responses": ["x"]}).status_code == 404
