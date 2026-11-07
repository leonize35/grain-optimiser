"""Partial tipping (docs/DOMAIN_DECISIONS.md R2 `partial`, confirmed by the user 2026-11-07 for loads above the pit
size): the truck tips what fits, then waits on the hopper for space for the remainder. Hand-traced. Test inputs only.

A truck may start (or resume) when the pit's free space is at least min(remaining load, `tip_portion_min_t`). It
tips min(remaining, free space); a portion takes the share of the truck's tipping time equal to its share of the
load (cumulative rounding, so the portions add up to the whole tipping time), and becomes a lot that drains. The
truck keeps the hopper between portions.

Site: one hopper H1 (pit 30 t, discharge 60 t/h = 1 t/min) -> C1 -> E1 -> B1 (1 800 t/h, so the pit drains at 1 t/min).
Sequence: tip only. Tipping time 10 min for the whole load.
"""
import copy

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config, validate
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel

S = 1000  # ms
RAW = {
    "id": "partial", "name": "Partial tipping test site", "version": 1, "hours": {"open": 7, "close": 18},
    "commodities": [{"id": "YM", "name": "Yellow maize"}],
    "equipment": [
        {"id": "H1", "type": "hopper", "name": "H1", "capT": 30, "rate": 60, "tip": [10, 10, 10], "commodities": ["YM"],
         "tip_admission": "partial"},
        {"id": "C1", "type": "conveyor", "name": "C1", "rate": 1800},
        {"id": "E1", "type": "elevator", "name": "E1", "rate": 1800},
        {"id": "B1", "type": "bin", "name": "B1", "capT": 5000, "commodities": ["YM"]}],
    "edges": [["H1", "C1"], ["C1", "E1"], ["E1", "B1"]],
    "sequences": {"unload": ["tip"]}, "demand": {}, "changeovers": {"default_minutes": 0}}
TIMES = FixedServiceTimes({"tip": 10, "tip:position": 2})


def raw(**hopper):
    r = copy.deepcopy(RAW)
    r["equipment"][0].update(hopper)
    return r


def run(r, trucks=(("T1", "07:00", 40),)):
    s = load_site_config(r)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": kg} for t, at, kg in trucks]})
    m = TruckFlowModel(s, script, TIMES, policy="feasible_first").run()
    audit = audit_flow(s, script, m)
    assert m.violations == [] and m.material_balance_kg == 0 and m.stall is None
    assert audit.ok, audit.problems
    return m


def tip(r, truck="T1"):
    rec = next(x for x in r.records if x.truck_id == truck)
    s = next(s for s in rec.steps if s.step == "tip")
    return s.started, s.finished


def lots(r, truck="T1"):
    return [(x.kg // 1000, x.tipped_at) for x in sorted(r.lots.values(), key=lambda x: x.tipped_at or 0) if x.truck_id == truck]


def test_a_load_larger_than_the_pit_tips_in_portions():
    """40 t into a 30 t pit. 07:00-07:07:30 the first 30 t (7.5 of 10 min); the pit then drains at 1 t/min, and
    each time 1 t is free the truck tips 1 t (15 s): ten more portions starting 07:08:30, 07:09:30, ..., 07:17:30.
    The truck finishes at 07:17:45; 11 lots, 40 t in total."""
    r = run(raw())
    assert tip(r) == (hm("07:00"), hm("07:17") + 45 * S)
    got = lots(r)
    assert got[0] == (30, hm("07:07") + 30 * S) and len(got) == 11 and sum(kg for kg, _ in got) == 40
    assert [t for _, t in got[1:]] == [hm("07:08") + 45 * S + i * 60 * S for i in range(10)]
    assert r.received_kg == 40_000


def test_a_larger_minimum_portion_means_fewer_waits():
    """Minimum portion 5 t: after the first 30 t (07:07:30) the truck waits until 5 t are free (07:12:30), tips 5 t
    in 1.25 min (to 07:13:45), waits until 5 t are free again (07:17:30) and tips the last 5 t to 07:18:45."""
    r = run(raw(tip_portion_min_t=5))
    assert tip(r) == (hm("07:00"), hm("07:18") + 45 * S)
    assert lots(r) == [(30, hm("07:07") + 30 * S), (5, hm("07:13") + 45 * S), (5, hm("07:18") + 45 * S)]


def test_a_load_that_fits_tips_exactly_as_before():
    """20 t fits: one lot, tipping 07:00-07:10, the same as full_load_space."""
    partial = run(raw(), trucks=(("T1", "07:00", 20),))
    full = run(raw(tip_admission="full_load_space"), trucks=(("T1", "07:00", 20),))
    assert tip(partial) == tip(full) == (hm("07:00"), hm("07:10"))
    assert lots(partial) == lots(full) == [(20, hm("07:10"))]


def test_partial_tipping_with_unloading_tasks():
    """A positioning task (1 worker, 2 min) before the discharge: the first portion's pit space is claimed with the
    hopper at 07:00, positioning 07:00-07:02, then the 40 t discharge in portions: first 30 t 07:02-07:09:30, the rest
    as in the first test shifted by 2 min: done 07:19:45."""
    r = raw()
    r["operator_pools"] = [{"id": "crew", "skills": ["tip"], "schedule": [{"from": "07:00", "to": "18:00", "count": 1}]}]
    r["unloading_labour"] = {"pool": "crew", "tasks": [{"id": "position", "operators": 1, "time": [2, 2, 2]},
                                                       {"id": "discharge", "operators": 0, "time": "tip"}]}
    m = run(r)
    assert tip(m) == (hm("07:00"), hm("07:19") + 45 * S)
    assert lots(m)[0] == (30, hm("07:09") + 30 * S) and sum(kg for kg, _ in lots(m)) == 40


def test_a_second_truck_waits_for_the_hopper_not_the_pit():
    """T2 (20 t) arrives 07:01 while T1 is still tipping in portions: it waits for the hopper, which T1 holds until
    07:17:45. T2 then tips as soon as 1 t is free (portions), finishing after T1."""
    m = run(raw(), trucks=(("T1", "07:00", 40), ("T2", "07:01", 20)))
    assert tip(m, "T2")[0] >= hm("07:17") + 45 * S and sum(kg for kg, _ in lots(m, "T2")) == 20


def test_the_check_accepts_loads_above_the_pit_when_tipping_is_partial():
    big = raw()
    big["demand"] = {"unload": {"daily": 10, "payload": [30, 40, 47], "mix": {"YM": 1}}}
    assert not [i for i in validate(load_site_config(big)).errors if "exceeds every hopper capacity" in i.msg]
    full = raw(tip_admission="full_load_space")
    full["demand"] = big["demand"]
    assert [i for i in validate(load_site_config(full)).errors if "exceeds every hopper capacity" in i.msg]


def test_minimum_portion_must_be_positive():
    with pytest.raises(ModelError, match="minimum tipping portion"):
        run(raw(tip_portion_min_t=0))


def test_audit_detects_a_truck_whose_lots_do_not_add_up():
    r = raw()
    s = load_site_config(r)
    script = load_arrival_script({"trucks": [{"id": "T1", "activity": "unload", "arrive": "07:00", "commodity": "YM", "tonnes": 40}]})
    m = TruckFlowModel(s, script, TIMES, policy="feasible_first").run()
    last = max(m.lots.values(), key=lambda x: x.tipped_at or 0)
    del m.lots[last.lot_id]
    m.transfers = [x for x in m.transfers if x.lot_id != last.lot_id]
    assert any("delivered" in p for p in audit_flow(s, script, m).problems)
