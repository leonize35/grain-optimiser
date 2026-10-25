"""Unified pre-run report (docs/PLATFORM_GAP_ANALYSIS.md step 1, gap G9): both validators in one list with code,
severity, location, message and fix, plus platform checks the validators did not make. Configurations are test
inputs."""
import copy
import json

from silo_engine.config import load_site_config, validate
from silo_engine.config.report import prerun_report
from test_grading_blocking import RAW as GRADING, paths
from test_outcomes_clearance import RAW as CLEARANCE
from test_unloading_labour import site as two_silo_site


def report(raw):
    return prerun_report(load_site_config(copy.deepcopy(raw)))


def codes(r):
    return [f.code for f in r.findings]


def test_a_valid_site_has_no_errors_and_no_platform_warnings():
    r = report(CLEARANCE)
    assert r.ok and not [f for f in r.findings if f.source == "platform"]


def test_both_validators_appear_in_one_report_with_locations():
    raw = copy.deepcopy(CLEARANCE)
    raw["edges"].append(["E1", "GHOST"])  # structure: unknown equipment
    raw["hours"]["admission_cutoff"] = 7.5  # rules: cut-off after closing (07:24)
    r = report(raw)
    assert not r.ok
    sources = {f.source for f in r.findings if f.severity == "error"}
    assert sources == {"structure", "rules"}
    legacy = validate(load_site_config(raw))
    assert [f.message for f in r.findings if f.source == "structure" and f.severity == "error"] == \
        [i.msg for i in legacy.errors]  # wording kept exactly
    assert all(f.code and f.severity in ("error", "warning", "note") for f in r.findings)


def test_report_is_machine_readable():
    d = report(CLEARANCE).as_dict()
    json.dumps(d)
    assert set(d) == {"ok", "errors", "warnings", "notes", "findings"}
    assert all(set(f) == {"code", "severity", "source", "message", "location", "fix"} for f in d["findings"])


# (a) a hold after a station without an explicit truck path
def test_hold_without_explicit_path_is_warned():
    r = report(GRADING)  # sequence sample -> weigh_in -> grade -> ..., no truck path
    f = next(f for f in r.findings if f.code == "process.hold_without_path")
    assert f.severity == "warning" and f.location == ["unload", "weigh_in"] and "truck path" in f.fix
    assert "process.hold_without_path" not in codes(report({**GRADING, **paths()}))
    plain = copy.deepcopy(GRADING)
    plain["sequences"]["unload"] = ["sample", "grade", "weigh_in", "tip", "weigh_out"]  # grading straight after sampling
    assert "process.hold_without_path" not in codes(report(plain))


# (b) clock times the engine cannot represent
def test_hours_not_in_whole_milliseconds_are_errors():
    raw = copy.deepcopy(CLEARANCE)
    raw["hours"]["admission_cutoff"] = 7 + 20 / 60  # 07:20 as a float is not exact
    f = next(f for f in report(raw).findings if f.code == "hours.not_representable")
    assert f.severity == "error" and f.location == ["hours", "admission_cutoff"] and "07:20" in f.fix
    assert "hours.not_representable" not in codes(report(CLEARANCE))  # 7.3 = 07:18 is exact


# (c) one day's expected receipts against free storage
def test_daily_receipts_beyond_free_storage_are_warned():
    raw = copy.deepcopy(CLEARANCE)
    raw["demand"] = {"unload": {"daily": 200, "payload": [30, 30, 30], "mix": {"YM": 1}}}  # 6 000 t > 5 000 t
    f = next(f for f in report(raw).findings if f.code == "storage.daily_receipts_exceed_space")
    assert f.severity == "warning" and f.location == ["YM"]
    raw["demand"]["unload"]["daily"] = 100  # 3 000 t
    assert "storage.daily_receipts_exceed_space" not in codes(report(raw))


# (d) services allowed after the last shift of a pool the process needs
def test_overtime_beyond_worker_shifts_is_warned():
    raw = two_silo_site(workers=2)
    raw["hours"] = {"open": 7, "close": 18, "overtime": 2}  # services until 20:00; unloaders work until 18:00
    f = next(f for f in report(raw).findings if f.code == "labour.no_workers_in_overtime")
    assert f.severity == "warning" and f.location == ["unloaders"] and "18:00" in f.message and "20:00" in f.message
    raw["hours"]["overtime"] = 0
    assert "labour.no_workers_in_overtime" not in codes(report(raw))


# (e) waiting areas and stations no truck can use
def test_unused_areas_and_stations_are_warned():
    raw = {**copy.deepcopy(GRADING), **paths()}
    raw["truck_areas"].append({"id": "spare", "name": "Spare lane", "capacity": 2})
    raw["equipment"].append({"id": "WB_X", "type": "weighbridge", "name": "Spare bridge", "cap": 1, "moves": "in",
                             "time": [2, 2, 2], "activities": ["load"]})  # no loading trucks in this site's process
    r = report(raw)
    assert next(f for f in r.findings if f.code == "places.unused_area").location == ["spare"]
    assert next(f for f in r.findings if f.code == "stations.unused").location == ["WB_X"]
    assert not {"places.unused_area", "stations.unused"} & set(codes(report({**GRADING, **paths()})))
