"""Finite waiting areas, truck paths, blocking after service and the deadlock policy (R5, A6). Build step 6.

Site: weighbridge WB1 (one lane, weighs in and out, 2 min), hopper H1 (200 t pit, tipping 10 min) feeding
C1 -> E1 -> B1, so grain transfers never limit tipping here. Four trucks of 30 t yellow maize all arrive 07:00.
Areas: "gate" (road queue, unlimited) and "yard" (space between weighbridge and hopper, 1 truck).
"""
import copy

from silo_engine.config import load_site_config
from silo_engine.config.rules_validation import validate_rules
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.ledger import AreaClaim, LaneClaim, ReservationLedger
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import TruckFlowModel

BASE = {
    "id": "s", "name": "Staging silo", "version": 1, "hours": {"open": 7, "close": 18},
    "commodities": [{"id": "YM", "name": "Yellow maize"}],
    "equipment": [
        {"id": "WB1", "type": "weighbridge", "name": "Weighbridge", "cap": 1, "time": [2, 2, 2]},
        {"id": "H1", "type": "hopper", "name": "Hopper 1", "capT": 200, "rate": 400, "tip": [10, 10, 10],
         "commodities": ["YM"]},
        {"id": "C1", "type": "conveyor", "name": "C1", "rate": 300},
        {"id": "E1", "type": "elevator", "name": "E1", "rate": 200},
        {"id": "B1", "type": "bin", "name": "Bin 1", "capT": 5000, "commodities": ["YM"]},
    ],
    "edges": [["H1", "C1"], ["C1", "E1"], ["E1", "B1"]],
    "sequences": {"unload": ["weigh_in", "tip"]},
    "demand": {},
}
AREAS = [{"id": "gate", "name": "Road queue", "capacity": None}, {"id": "yard", "name": "Hopper waiting area", "capacity": 1}]
TIMES = FixedServiceTimes({"weigh_in": 2, "weigh_out": 2, "tip": 10})


def raw(**changes):
    r = copy.deepcopy(BASE)
    r.update(changes)
    return r


def trucks(n):
    return load_arrival_script({"trucks": [
        {"id": f"T{i}", "activity": "unload", "arrive": "07:00", "commodity": "YM", "tonnes": 30} for i in range(1, n + 1)]})


def model(r, n=4):
    return TruckFlowModel(load_site_config(r), trucks(n), TIMES, policy="feasible_first")


def step(result, truck_id, name):
    rec = next(x for x in result.records if x.truck_id == truck_id)
    return next(s for s in rec.steps if s.step == name)


def weigh_times(result):
    return {t: (step(result, t, "weigh_in").started, step(result, t, "weigh_in").left) for t in ("T1", "T2", "T3", "T4")}


def tip_starts(result):
    return {t: step(result, t, "tip").started for t in ("T1", "T2", "T3", "T4")}


# Without blocking (hand-derived): weighing 07:00, 07:02, 07:04, 07:06, each leaving the weighbridge after 2 min;
# tipping 07:02, 07:12, 07:22, 07:32 (the hopper is the bottleneck).
FREE_WEIGH = {"T1": (hm("07:00"), hm("07:02")), "T2": (hm("07:02"), hm("07:04")),
              "T3": (hm("07:04"), hm("07:06")), "T4": (hm("07:06"), hm("07:08"))}
TIPS = {"T1": hm("07:02"), "T2": hm("07:12"), "T3": hm("07:22"), "T4": hm("07:32")}


def test_unlimited_areas_reproduce_the_non_blocking_model():
    """T5.1: no truck path, or a path whose areas are all unlimited, gives the same times."""
    implicit = model(raw()).run()
    unlimited = model(raw(truck_areas=[{**a, "capacity": None} for a in AREAS],
                          truck_paths={"unload": ["gate", "weigh_in", "yard", "tip"]})).run()
    for result in (implicit, unlimited):
        assert result.stall is None and result.violations == [] and result.material_balance_kg == 0
        assert weigh_times(result) == FREE_WEIGH
        assert tip_starts(result) == TIPS


BLOCKING = raw(truck_areas=AREAS, truck_paths={"unload": ["gate", "weigh_in", "yard", "tip"]},
               deadlock_prevention="detect_only")


def test_full_yard_keeps_a_weighed_truck_on_the_weighbridge():
    """T5.2 (yard holds 1). T1: weighed 07:00-07:02, through the yard, tips 07:02. T2: weighed 07:02-07:04, waits
    in the yard. T3: weighed 07:04-07:06 but the yard is full: it stays on the weighbridge until T2 starts tipping
    at 07:12. T4 can only weigh in once T3 has left: 07:12-07:14, then blocks the weighbridge until 07:22.
    Tipping is unchanged (the hopper is still the bottleneck)."""
    result = model(BLOCKING).run()
    assert result.stall is None and result.violations == [] and result.material_balance_kg == 0
    assert weigh_times(result) == {"T1": (hm("07:00"), hm("07:02")), "T2": (hm("07:02"), hm("07:04")),
                                   "T3": (hm("07:04"), hm("07:12")), "T4": (hm("07:12"), hm("07:22"))}
    assert step(result, "T3", "weigh_in").finished == hm("07:06")  # service ended; blocked 6 min
    assert tip_starts(result) == TIPS


def test_waiting_reasons_show_the_blocking_chain():
    m = model(BLOCKING)
    m.run(until=hm("07:08"))
    reasons = {rid: [r.code for r in rs] for rid, rs in m.waiting_reasons().items()}
    assert reasons["T3/enter:yard"] == ["AREA_FULL"]
    assert reasons["T4/weigh_in"] == ["EQUIPMENT_BUSY"]
    assert reasons["T2/tip"] == ["EQUIPMENT_BUSY"]


CYCLE = dict(truck_areas=AREAS, truck_paths={"unload": ["gate", "weigh_in", "yard", "tip", "weigh_out"]},
             sequences={"unload": ["weigh_in", "tip", "weigh_out"]})


def test_detect_only_reports_a_deadlock_and_stops():
    """T5.3 detect_only, three trucks, weigh-out straight after tipping (no area between hopper and weighbridge).
    07:12: T1 finishes tipping and needs the weighbridge, which T3 occupies while waiting for the yard, which T2
    occupies while waiting for the hopper, which T1 occupies: a circular wait. T1's lot still flows to the bin
    (07:12-07:21); after that nothing can change, so the run stops at 07:21 and reports the stall."""
    result = model(raw(**CYCLE, deadlock_prevention="detect_only"), n=3).run()
    assert result.stall is not None
    assert result.stall.time == hm("07:21")
    assert {rid: [r.code for r in rs] for rid, rs in result.stall.waiting.items()} == {
        "T1/weigh_out": ["EQUIPMENT_BUSY"], "T2/tip": ["EQUIPMENT_BUSY"], "T3/enter:yard": ["AREA_FULL"]}
    assert sorted(u.truck_id for u in result.unfinished) == ["T1", "T2", "T3"]
    assert result.material_balance_kg == 0 and result.violations == []


def test_reserve_next_space_prevents_the_deadlock():
    """T5.3 with reserve_next_space: a truck may start weighing in only with a yard place reserved.
    T1 07:00-07:02, tips 07:02-07:12, weighs out 07:12-07:14. T2 weighs in 07:02-07:04 (yard free once T1 tips).
    T3 cannot weigh in while T2 holds the yard: the weighbridge stays free, so T1 can weigh out at 07:12.
    T3 weighs in 07:14-07:16, tips 07:22-07:32, weighs out 07:32-07:34. T2 tips 07:12-07:22, out 07:22-07:24."""
    result = model(raw(**CYCLE, deadlock_prevention="reserve_next_space"), n=3).run()
    assert result.stall is None and result.violations == [] and result.material_balance_kg == 0
    r = {x.truck_id: x for x in result.records}
    assert {t: r[t].departed for t in r} == {"T1": hm("07:14"), "T2": hm("07:24"), "T3": hm("07:34")}
    assert step(result, "T3", "weigh_in").started == hm("07:14")
    assert step(result, "T1", "weigh_out").started == hm("07:12")


def test_simplifications_are_listed_in_the_run_assumptions():
    implicit = model(raw()).run()
    assert "Unloading trucks have unlimited waiting space between steps (no truck path configured)." in implicit.assumptions
    explicit = model(BLOCKING).run()
    assert "Waiting area Road queue has unlimited space." in explicit.assumptions
    assert not any(a.startswith("Unloading trucks have unlimited") for a in explicit.assumptions)


def test_truck_path_must_match_the_sequence_and_known_areas():
    bad = raw(truck_areas=AREAS + [{"id": "tip", "name": "Odd", "capacity": 2}],
              truck_paths={"unload": ["gate", "weigh_in", "lot", "tip"]})
    msgs = [i.msg for i in validate_rules(load_site_config(bad)).errors]
    assert msgs == ["Waiting area id tip is also the name of a truck step; choose another id.",
                    "The unloading truck path refers to unknown waiting area lot."]
    mismatch = raw(truck_areas=AREAS, truck_paths={"unload": ["gate", "yard", "tip"]})
    assert [i.msg for i in validate_rules(load_site_config(mismatch)).errors] == [
        "The unloading truck path's steps (tip) do not match the unloading sequence (weigh_in, tip)."]


def test_ledger_reserves_a_lane_and_the_next_area_together_or_not_at_all():
    ledger = ReservationLedger(lanes={"WB1#0"}, segments={}, pits={}, bins={}, areas={"yard": 1})
    assert ledger.try_reserve("A", [AreaClaim("yard")], 0) == []
    before = ledger.snapshot()
    reasons = ledger.try_reserve_many([("B", [LaneClaim("WB1#0")]), ("B-area", [AreaClaim("yard")])], 0)
    assert [r.code for r in reasons] == ["AREA_FULL"]
    assert ledger.snapshot() == before and ledger.lane_free("WB1#0")
    ledger.release("A", 1, "completed")
    assert ledger.try_reserve_many([("B", [LaneClaim("WB1#0")]), ("B-area", [AreaClaim("yard")])], 1) == []
    assert ledger.area_occupancy("yard") == 1 and ledger.check_invariants(1) == []
