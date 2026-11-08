"""Dirty-load cleaning route (gap G-D4; rules confirmed by the user 2026-11-07). Hand-traced. Test inputs only.

- Grading decides whether a load is dirty. A dirty load must reach its bin through a cleaner; a clean load must take
  a route without a cleaner (the bypass), never the cleaner.
- A cleaner (equipment type `cleaner`) is a route segment with a rate; `screenings` gives, per commodity, the share
  of a dirty load it removes. The screenings are a recorded loss (cause "cleaning"); the rest reaches the bin, and
  grain conservation is still checked.
- Assumption (to confirm): a pit holds dirty or clean grain, not both at once, as with two commodities (A4).
- Demand: `dirty_share` per commodity gives each generated truck's chance of being dirty (its own random stream);
  scripted trucks give `dirty` directly. Dirty status is used only after the truck's grading result.

Site: sampler 1 min, grader 1 min, hopper H1 (60 t pit, 1 800 t/h, tip 5 min) -> C1 -> either bypass BY1
(1 800 t/h) or cleaner CL1 (360 t/h, removes 2 % of a dirty load of YM) -> E1 -> bin B1. Sequence sample, grade, tip.
T1 (clean, 30 t) and T2 (dirty, 30 t) arrive 07:00.
T1: sampled 07:00-01, graded 07:01-02, tips 07:02-07; its lot drains over the bypass 07:07-08 (30 t at 30 t/min).
T2: sampled 07:01-02, graded 07:02-03; the hopper is busy until 07:07 and then holds T1's clean grain until 07:08,
so T2 tips 07:08-13; its lot drains through the cleaner 07:13-18 (30 t at 6 t/min): 600 kg screenings, 29 400 kg
into B1.
"""
import copy

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config, validate
from silo_engine.config.rules_validation import validate_rules
from silo_engine.inputs.generated import generate_arrivals
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import TruckFlowModel

RAW = {
    "id": "cleaning", "name": "Cleaning test site", "version": 1, "hours": {"open": 7, "close": 18},
    "commodities": [{"id": "YM", "name": "Yellow maize"}],
    "equipment": [
        {"id": "S1", "type": "sampler", "name": "Sampler", "cap": 1, "time": [1, 1, 1]},
        {"id": "G1", "type": "grader", "name": "Grader", "cap": 1, "time": [1, 1, 1]},
        {"id": "H1", "type": "hopper", "name": "H1", "capT": 60, "rate": 1800, "tip": [5, 5, 5], "commodities": ["YM"]},
        {"id": "C1", "type": "conveyor", "name": "C1", "rate": 1800},
        {"id": "BY1", "type": "conveyor", "name": "Bypass", "rate": 1800},
        {"id": "CL1", "type": "cleaner", "name": "Cleaner", "rate": 360, "screenings": {"YM": 0.02}},
        {"id": "E1", "type": "elevator", "name": "E1", "rate": 1800},
        {"id": "B1", "type": "bin", "name": "B1", "capT": 5000, "commodities": ["YM"]}],
    "edges": [["H1", "C1"], ["C1", "BY1"], ["C1", "CL1"], ["BY1", "E1"], ["CL1", "E1"], ["E1", "B1"]],
    "sequences": {"unload": ["sample", "grade", "tip"]},
    "demand": {}, "changeovers": {"default_minutes": 0}}
TIMES = FixedServiceTimes({"sample": 1, "grade": 1, "tip": 5})


def run(raw=RAW, trucks=(("T1", "07:00", False), ("T2", "07:00", True))):
    s = load_site_config(copy.deepcopy(raw))
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": 30, "dirty": d}
        for t, at, d in trucks]})
    r = TruckFlowModel(s, script, TIMES, policy="feasible_first").run()
    audit = audit_flow(s, script, r)
    assert r.violations == [] and r.material_balance_kg == 0 and r.stall is None
    assert audit.ok, audit.problems
    return r


def tip(r, t):
    s = next(s for x in r.records if x.truck_id == t for s in x.steps if s.step == "tip")
    return s.started, s.finished


def test_dirty_loads_go_through_the_cleaner_and_clean_loads_take_the_bypass():
    r = run()
    assert (tip(r, "T1"), tip(r, "T2")) == ((hm("07:02"), hm("07:07")), (hm("07:08"), hm("07:13")))
    t1, t2 = (next(x for x in r.transfers if x.truck_id == t) for t in ("T1", "T2"))
    assert (t1.path, t1.started, t1.finished, t1.kg, r.screenings.get(t1.id, (0,))[0]) == (
        ["H1", "C1", "BY1", "E1", "B1"], hm("07:07"), hm("07:08"), 30000, 0)
    assert (t2.path, t2.started, t2.finished, t2.kg, r.screenings[t2.id][0]) == (
        ["H1", "C1", "CL1", "E1", "B1"], hm("07:13"), hm("07:18"), 30000, 600)


def test_screenings_are_a_recorded_loss_and_grain_is_conserved():
    r = run()
    assert r.bins["B1"][0] == 59400
    assert [(x.bin, x.commodity, x.kg, x.cause, x.time) for x in r.losses] == [("CL1", "YM", 600, "cleaning", hm("07:18"))]
    assert r.received_kg == 60000  # tipped; the balance closes with the loss (checked in run())


def test_a_pit_does_not_mix_dirty_and_clean_grain():
    """T2 waits 07:07-07:08 because the pit still holds T1's clean grain."""
    r = run()
    causes = {k: v for cell in r.wait_causes["truck"].values() for k, v in cell.items()}
    assert causes.get("PIT_INCOMPATIBLE:H1") == 1


def test_routes_for_dirty_and_clean_grain():
    from silo_engine.sim.truck_flow import TruckFlowModel as M
    s = load_site_config(copy.deepcopy(RAW))
    m = M(s, load_arrival_script({"trucks": []}), TIMES)
    g = next(iter(m.bins["B1"].accepts))
    assert m.planner.intake_candidates("H1", g) == [["H1", "C1", "BY1", "E1", "B1"]]
    assert m.planner.intake_candidates("H1", g, dirty=True) == [["H1", "C1", "CL1", "E1", "B1"]]


def test_without_dirty_loads_nothing_changes():
    """Two clean loads: both over the bypass, no screenings; T2 shares the pit with T1 (60 t)."""
    r = run(trucks=(("T1", "07:00", False), ("T2", "07:00", False)))
    assert all(x.path[2] == "BY1" for x in r.transfers) and r.losses == []
    assert tip(r, "T2") == (hm("07:07"), hm("07:12"))


def test_generated_trucks_get_a_dirty_status_from_their_own_stream():
    raw = copy.deepcopy(RAW)
    raw["demand"] = {"unload": {"daily": 200, "mix": {"YM": 1}, "payload": [20, 25, 30]}}
    a = generate_arrivals(load_site_config(copy.deepcopy(raw)), seed=5)
    raw["demand"]["unload"]["dirty_share"] = {"YM": 0.25}
    b = generate_arrivals(load_site_config(raw), seed=5)
    assert [(t.id, t.arrive_ms, t.kg) for t in a] == [(t.id, t.arrive_ms, t.kg) for t in b]
    assert all(t.dirty is None for t in a)
    share = sum(t.dirty for t in b) / len(b)
    assert 0.15 < share < 0.35


@pytest.mark.parametrize("change, words", [
    (lambda r: r["equipment"].__setitem__(5, {**r["equipment"][5], "screenings": {"YM": 1.0}}), "screenings"),
    (lambda r: r.update(edges=[e for e in r["edges"] if "CL1" not in e]), "no route through a cleaner"),
    (lambda r: r.update(edges=[e for e in r["edges"] if "BY1" not in e]), "without a cleaner"),
    (lambda r: r["sequences"].update(unload=["sample", "tip", "grade"]), "graded before"),
])
def test_invalid_cleaning_setups_are_refused(change, words):
    raw = copy.deepcopy(RAW)
    raw["demand"] = {"unload": {"daily": 10, "mix": {"YM": 1}, "payload": [20, 25, 30], "dirty_share": {"YM": 0.2}}}
    change(raw)
    s = load_site_config(raw)
    msgs = [i.msg for i in validate(s).errors] + [i.msg for i in validate_rules(s).errors]
    assert any(words in m for m in msgs), msgs
