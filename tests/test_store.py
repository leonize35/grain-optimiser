"""Configuration store: versions, history, diff and scenario overlays (docs/PLATFORM_GAP_ANALYSIS.md step 7, G10).
Every test uses a temporary folder; the store never writes inside the repository."""
import copy
import json
from pathlib import Path

import pytest

from silo_engine.config import ConfigSchemaError, load_site_config
from silo_engine.config.schema import config_hash
from silo_engine.store import ConfigStore, StoreError, apply_overlay, diff_configs
from test_outcomes_clearance import RAW

ROOT = Path(__file__).resolve().parents[1]


def base():
    return copy.deepcopy(RAW)


def test_save_load_round_trip_keeps_the_hash(tmp_path):
    store = ConfigStore(tmp_path)
    v = store.save(base(), note="first draft")
    assert v.version == 1 and v.site_id == "clearance"
    loaded = store.load("clearance")
    assert config_hash(load_site_config(loaded)) == v.config_hash
    assert loaded["version"] == 1  # the store numbers versions


def test_versions_are_immutable_and_listed_in_history(tmp_path):
    store = ConfigStore(tmp_path)
    store.save(base(), note="first")
    changed = base()
    changed["hours"]["overtime"] = 1
    store.save(changed, note="longer overtime")
    h = store.history("clearance")
    assert [(e["version"], e["note"]) for e in h] == [(1, "first"), (2, "longer overtime")]
    assert store.load("clearance", 1)["hours"]["overtime"] == 0.5 and store.load("clearance")["hours"]["overtime"] == 1
    assert h[1]["parent"] == 1 and h[0]["config_hash"] != h[1]["config_hash"]
    with pytest.raises(StoreError):
        store._write_version("clearance", 1, base())  # an existing version is never overwritten
    assert store.list_sites() == ["clearance"]


def test_unreadable_configurations_are_refused_and_drafts_record_their_report(tmp_path):
    store = ConfigStore(tmp_path)
    bad = base()
    bad["equipment"][0]["capacity"] = 3  # misspelt field
    with pytest.raises(ConfigSchemaError):
        store.save(bad)
    draft = base()
    draft["edges"].append(["E1", "GHOST"])  # readable, but cannot run
    v = store.save(draft, note="work in progress")
    assert (v.report["ok"], v.report["errors"] > 0) == (False, True)
    assert store.history("clearance")[0]["report"]["ok"] is False


def test_site_ids_must_be_safe_folder_names(tmp_path):
    bad = base()
    bad["id"] = "../outside"
    with pytest.raises(StoreError):
        ConfigStore(tmp_path).save(bad)


def test_diff_lists_exactly_what_changed():
    a, b = base(), base()
    b["equipment"] = [e for e in b["equipment"] if e["id"] != "WB_OUT"]  # removed
    b["equipment"].append({"id": "H2", "type": "hopper", "name": "H2", "capT": 60, "rate": 900, "tip": [5, 5, 5],
                           "commodities": ["YM"]})  # added
    next(e for e in b["equipment"] if e["id"] == "H1")["rate"] = 900  # changed
    b["edges"].append(["H2", "C1"])
    b["hours"]["overtime"] = 1
    assert diff_configs(a, b) == [
        {"kind": "changed", "where": "equipment H1", "field": "rate", "from": 1800, "to": 900},
        {"kind": "added", "where": "equipment H2"},
        {"kind": "removed", "where": "equipment WB_OUT"},
        {"kind": "added", "where": "edge H2 -> C1"},
        {"kind": "changed", "where": "hours", "field": "overtime", "from": 0.5, "to": 1},
    ]
    assert diff_configs(a, copy.deepcopy(a)) == []


def test_overlay_builds_a_scenario_without_touching_the_base():
    b = base()
    before = json.dumps(b, sort_keys=True)
    ops = [{"op": "set", "path": "hours.overtime", "value": 2},
           {"op": "add_equipment", "item": {"id": "H2", "type": "hopper", "name": "H2", "capT": 60, "rate": 900,
                                            "tip": [5, 5, 5], "commodities": ["YM"]}},
           {"op": "add_edge", "edge": ["H2", "C1"]},
           {"op": "update_equipment", "id": "WB_IN", "fields": {"cap": 2}},
           {"op": "remove_edge", "edge": ["E1", "B1"]}, {"op": "add_edge", "edge": ["E1", "B1"]}]
    s = apply_overlay(b, ops)
    assert json.dumps(b, sort_keys=True) == before
    assert s["hours"]["overtime"] == 2 and next(e for e in s["equipment"] if e["id"] == "WB_IN")["cap"] == 2
    assert ["H2", "C1"] in s["edges"] and [e["kind"] for e in diff_configs(b, s)] == ["changed", "added", "added", "changed"]
    load_site_config(s)


@pytest.mark.parametrize("op, words", [
    ({"op": "update_equipment", "id": "GHOST", "fields": {"cap": 2}}, "no equipment GHOST"),
    ({"op": "remove_equipment", "id": "GHOST"}, "no equipment GHOST"),
    ({"op": "add_equipment", "item": {"id": "H1", "type": "hopper", "name": "again"}}, "already has equipment H1"),
    ({"op": "remove_edge", "edge": ["H1", "B1"]}, "no edge H1 -> B1"),
    ({"op": "set", "path": "hours.nonsense.deep", "value": 1}, "no field"),
    ({"op": "teleport"}, "unknown overlay operation"),
])
def test_invalid_overlay_operations_are_refused(op, words):
    with pytest.raises(StoreError, match=words):
        apply_overlay(base(), [op])


def test_scenarios_are_stored_against_a_base_version(tmp_path):
    store = ConfigStore(tmp_path)
    store.save(base(), note="baseline")
    store.save_scenario("clearance", "more_overtime", base_version=1, ops=[{"op": "set", "path": "hours.overtime", "value": 2}])
    sc = store.load_scenario("clearance", "more_overtime")
    assert sc["base_version"] == 1 and sc["config"]["hours"]["overtime"] == 2
    assert store.load("clearance")["hours"]["overtime"] == 0.5  # the base is unchanged
    assert store.list_scenarios("clearance") == ["more_overtime"]


def test_a_synthetic_site_survives_the_store_with_its_published_hash(tmp_path):
    raw = json.loads((ROOT / "evidence" / "configs" / "site_a.json").read_text(encoding="utf-8"))
    published = json.loads((ROOT / "evidence" / "out" / "paper2-v1" / "manifest.json").read_text(encoding="utf-8"))
    store = ConfigStore(tmp_path)
    raw_v = raw.get("version")
    v = store.save(raw, note="Site A")
    loaded = store.load(raw["id"])
    loaded["version"] = raw_v  # the store renumbers versions; with the original number the hash is the published one
    assert config_hash(load_site_config(loaded)) == published["configurations"]["A"]["config_hash"]
    assert v.version == 1
