"""Grades end to end (R4): commodity + grade drive pit and bin allocation; grading before tipping. Build step 5.

Common site: hopper H1 (60 t, yellow maize) -> C1 (300 t/h) -> E1 (200 t/h) -> bins. Route rate 200 t/h, so a
30 t lot flows for 9 min. Sampler 1 lane (2 min), grading lab 2 lanes (3 min), tipping 1 min.
Unloading sequence: sample, grade, tip.
  T1 arrives 07:00: sampled 07:00-07:02, graded 07:02-07:05, tips 07:05-07:06, lot flows 07:06-07:15.
  T2 arrives 07:00: sampled 07:02-07:04 (sampler busy until 07:02), graded 07:04-07:07, then tips when allowed.
"""
import copy

import pytest

from silo_engine.config import load_site_config
from silo_engine.config.rules_validation import validate_rules
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel


def t(tonnes):
    return round(tonnes * 1000)


BASE = {
    "id": "g", "name": "Graded silo", "version": 1, "hours": {"open": 7, "close": 18},
    "commodities": [{"id": "YM", "name": "Yellow maize", "grades": ["1", "2", "3"]}],
    "equipment": [
        {"id": "S1", "type": "sampler", "name": "Sampler", "cap": 1, "time": [2, 2, 2]},
        {"id": "G1", "type": "grader", "name": "Lab", "cap": 2, "time": [3, 3, 3]},
        {"id": "H1", "type": "hopper", "name": "Hopper 1", "capT": 60, "rate": 400, "tip": [1, 1, 1],
         "commodities": ["YM"]},
        {"id": "C1", "type": "conveyor", "name": "Pit conveyor", "rate": 300},
        {"id": "E1", "type": "elevator", "name": "Elevator 1", "rate": 200},
        {"id": "B1", "type": "bin", "name": "Bin 1", "capT": 1000, "commodities": ["YM"],
         "accepts": [{"commodity": "YM", "grades": ["1"]}]},
        {"id": "B2", "type": "bin", "name": "Bin 2", "capT": 1000, "commodities": ["YM"],
         "accepts": [{"commodity": "YM", "grades": ["2", "3"]}]},
    ],
    "edges": [["H1", "C1"], ["C1", "E1"], ["E1", "B1"], ["E1", "B2"]],
    "sequences": {"unload": ["sample", "grade", "tip"]},
    "demand": {},
}


def raw(**changes):
    r = copy.deepcopy(BASE)
    r.update(changes)
    return r


def equipment(r, eid):
    return next(e for e in r["equipment"] if e["id"] == eid)


TIMES = FixedServiceTimes({"sample": 2, "grade": 3, "tip": 1})


def trucks(*rows):
    out = []
    for tid, grade in rows:
        entry = {"id": tid, "activity": "unload", "arrive": "07:00", "commodity": "YM", "tonnes": 30}
        if grade is not None:
            entry["grade"] = grade
        out.append(entry)
    return load_arrival_script({"trucks": out})


def run(r, *rows, times=TIMES):
    result = TruckFlowModel(load_site_config(r), trucks(*rows), times, policy="feasible_first").run()
    assert result.material_balance_kg == 0 and result.violations == []
    return result


def tip(result, truck_id):
    rec = next(x for x in result.records if x.truck_id == truck_id)
    return next(s for s in rec.steps if s.step == "tip").started


def timeline(result):
    return [(x.truck_id, x.bin, x.flow_started, x.finished) for x in result.transfers]


def messages(issues):
    return [i.msg for i in issues]


# ---------------- running model ----------------

def test_each_grade_goes_only_to_a_bin_assigned_to_it():
    """T4.1: T1 is grade 2 -> Bin 2 (07:06-07:15). T2 is grade 1: graded 07:07, but the pit holds grade 2 until
    07:15 (no mixing rule), so it tips 07:15-07:16; its lot goes to Bin 1, 07:16-07:25 (a grade-only change needs
    no changeover without a grade rule)."""
    result = run(raw(), ("T1", "2"), ("T2", "1"))
    assert tip(result, "T2") == hm("07:15")
    assert timeline(result) == [("T1", "B2", hm("07:06"), hm("07:15")), ("T2", "B1", hm("07:16"), hm("07:25"))]
    assert result.bins == {"B1": (t(30), ("YM", "1")), "B2": (t(30), ("YM", "2"))}


def test_grade_change_uses_a_grade_level_changeover_rule():
    """As above with a rule yellow maize grade 2 -> grade 1: 4 min. T2's lot is reserved 07:16, flows 07:20-07:29."""
    r = raw(changeovers={"rules": [{"from": "YM:2", "to": "YM:1", "minutes": 4}]})
    result = run(r, ("T1", "2"), ("T2", "1"))
    assert timeline(result)[1] == ("T2", "B1", hm("07:20"), hm("07:29"))
    assert result.transfers[1].changeover_segments == {"C1": 240_000, "E1": 240_000}


def test_mixing_rule_lets_grades_share_pit_and_bin():
    """T4.2 with mixing {1, 2 -> 2}: only Bin 2 (grades 1 and 2, holding 100 t grade 2).
    T1 (grade 2) tips 07:05; T2 (grade 1) may tip onto it at 07:07-07:08 (30 t free).
    Lots flow 07:06-07:15 and 07:15-07:24. Bin 2: 160 t, still grade 2."""
    # Only grades 1 and 2 here, so that the single remaining bin can take every grade (T4.3 would refuse grade 3).
    r = raw(grade_mixing=[{"commodity": "YM", "grades": ["1", "2"], "result": "2"}],
            commodities=[{"id": "YM", "name": "Yellow maize", "grades": ["1", "2"]}])
    r["equipment"] = [e for e in r["equipment"] if e["id"] != "B1"]
    r["edges"] = [x for x in r["edges"] if x[1] != "B1"]
    equipment(r, "B2").update(accepts=[{"commodity": "YM", "grades": ["1", "2"]}], inv=100, invCommodity="YM",
                              invGrade="2")
    result = run(r, ("T1", "2"), ("T2", "1"))
    assert tip(result, "T2") == hm("07:07")
    assert timeline(result) == [("T1", "B2", hm("07:06"), hm("07:15")), ("T2", "B2", hm("07:15"), hm("07:24"))]
    assert result.bins == {"B2": (t(160), ("YM", "2"))}


def test_truck_cannot_tip_before_its_own_grading_result():
    """T4.4: T1's sample takes 10 min to grade (result 07:12), T2's 3 min (result 07:07). Both grade 1.
    T2 tips 07:07; T1 only after its own result, at 07:12."""
    times = FixedServiceTimes({"sample": 2, "grade": 3, "tip": 1}, overrides={("T1", "grade"): 10})
    result = run(raw(), ("T1", "1"), ("T2", "1"), times=times)
    assert (tip(result, "T2"), tip(result, "T1")) == (hm("07:07"), hm("07:12"))


def test_without_segregation_grades_are_recorded_but_do_not_restrict():
    """grade_segregation 'none': bins need no grade lists; T2 (grade 1) tips onto T1's grade-2 grain at 07:07."""
    r = raw(grade_segregation="none")
    for b in ("B1", "B2"):
        del equipment(r, b)["accepts"]
    result = run(r, ("T1", "2"), ("T2", "1"))
    assert tip(result, "T2") == hm("07:07")
    assert validate_rules(load_site_config(r)).errors == []


def test_graded_truck_must_state_a_known_grade():
    with pytest.raises(ModelError, match="T1.*grade"):
        TruckFlowModel(load_site_config(raw()), trucks(("T1", None)), TIMES, policy="feasible_first")
    with pytest.raises(ModelError, match="grade 9"):
        TruckFlowModel(load_site_config(raw()), trucks(("T1", "9")), TIMES, policy="feasible_first")


# ---------------- configuration checks ----------------

def test_valid_graded_site_has_no_rule_errors():
    assert validate_rules(load_site_config(raw())).errors == []


def test_bin_storing_a_graded_commodity_must_list_its_grades():
    r = raw()
    del equipment(r, "B1")["accepts"]
    assert messages(validate_rules(load_site_config(r)).errors) == [
        "Bin 1 stores Yellow maize, which has grades, but does not say which grades it accepts. "
        "List them, or set grade segregation to none."]


def test_a_grade_no_reachable_bin_accepts_is_an_error():
    """T4.3: Bin 2 accepts grade 2 only; nothing takes grade 3."""
    r = raw()
    equipment(r, "B2")["accepts"] = [{"commodity": "YM", "grades": ["2"]}]
    assert messages(validate_rules(load_site_config(r)).errors) == [
        "No storage bin reachable from a hopper accepts Yellow maize grade 3."]


def test_grading_after_tipping_is_an_error_when_grades_are_kept_apart():
    """T4.5"""
    r = raw(sequences={"unload": ["tip", "sample", "grade"]})
    assert messages(validate_rules(load_site_config(r)).errors) == [
        "Bins keep Yellow maize grades apart, but unloading trucks tip before they are graded. "
        "Put Grading before Unloading, or set grade segregation to none."]


def test_inconsistent_grade_settings_are_errors():
    r = raw(grade_mixing=[{"commodity": "YM", "grades": ["1", "4"], "result": "4"}])
    equipment(r, "B1")["accepts"] = [{"commodity": "WM", "grades": ["1"]}, {"commodity": "YM", "grades": ["1", "5"]}]
    equipment(r, "B2").update(inv=50, invCommodity="YM")
    assert messages(validate_rules(load_site_config(r)).errors) == [
        "Grade mixing for Yellow maize refers to grade 4, which is not one of its grades.",
        "Bin 1 lists grades for WM, which it does not store.",
        "Bin 1 accepts Yellow maize grade 5, which is not one of its grades.",
        "Bin 2 starts with Yellow maize but no grade; give the grade of the opening stock.",
    ]


def test_grade_lists_contradicting_no_segregation_are_errors():
    r = raw(grade_segregation="none")
    assert messages(validate_rules(load_site_config(r)).errors) == [
        "Bin 1 lists grades, but grade segregation is set to none.",
        "Bin 2 lists grades, but grade segregation is set to none."]


def test_ungraded_sites_are_unaffected():
    r = raw(commodities=[{"id": "YM", "name": "Yellow maize"}], sequences={"unload": ["tip"]})
    for b in ("B1", "B2"):
        del equipment(r, b)["accepts"]
    assert validate_rules(load_site_config(r)).errors == []
    result = run(r, ("T1", None), ("T2", None))
    assert result.bins["B1"] == (t(60), ("YM", "*"))
