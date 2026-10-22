"""Truck stations (sampler, grader, weighbridge) driven by the central dispatcher.

Build step 1 (docs/ENGINE_INTERFACES.md §7): unlimited waiting areas (R5 default), fixed service times,
scripted trucks. Every expected time below is derived by hand in the test's docstring.
"""
import pytest

from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, NotYetSupported, TruckFlowModel


def site(equipment, sequences):
    return load_site_config({
        "id": "test", "name": "Test silo", "version": 1,
        "hours": {"open": 6, "close": 18},
        "commodities": [{"id": "YM", "name": "Yellow maize"}],
        "equipment": equipment, "edges": [], "sequences": sequences,
        "demand": {},
    })


def wb(eid, cap=1, moves="both"):
    return {"id": eid, "type": "weighbridge", "name": eid, "cap": cap, "time": [2, 2, 2], "moves": moves}


def trucks(*rows):
    out = []
    for tid, activity, arrive in rows:
        entry = {"id": tid, "activity": activity, "arrive": arrive}
        if activity != "weigh":
            entry.update(commodity="YM", tonnes=30)
        out.append(entry)
    return load_arrival_script({"trucks": out})


def times(rec, step):
    s = next(r for r in rec.steps if r.step == step)
    return s.started, s.finished


TWO_MIN = FixedServiceTimes({"sample": 2, "grade": 2, "weigh_in": 2, "weigh_out": 2})


def test_single_weighbridge_serves_in_arrival_order():
    """One weighbridge, 2 min each. Arrivals 07:00, 07:01, 07:01.
    T1 07:00-07:02; T2 waits 1 min, 07:02-07:04; T3 waits 3 min, 07:04-07:06."""
    model = TruckFlowModel(site([wb("WB1")], {"weigh": ["weigh_in"]}),
                           trucks(("T1", "weigh", "07:00"), ("T2", "weigh", "07:01"), ("T3", "weigh", "07:01")),
                           TWO_MIN, policy="feasible_first")
    result = model.run()
    r = {x.truck_id: x for x in result.records}
    assert [times(r[t], "weigh_in") for t in ("T1", "T2", "T3")] == [
        (hm("07:00"), hm("07:02")), (hm("07:02"), hm("07:04")), (hm("07:04"), hm("07:06"))]
    assert {t: r[t].departed for t in r} == {"T1": hm("07:02"), "T2": hm("07:04"), "T3": hm("07:06")}
    assert result.unfinished == []


def test_capacity_two_serves_two_at_once():
    """Weighbridge with 2 lanes. Three trucks at 07:00: T1 and T2 07:00-07:02, T3 07:02-07:04."""
    model = TruckFlowModel(site([wb("WB1", cap=2)], {"weigh": ["weigh_in"]}),
                           trucks(("T1", "weigh", "07:00"), ("T2", "weigh", "07:00"), ("T3", "weigh", "07:00")),
                           TWO_MIN, policy="feasible_first")
    r = {x.truck_id: x for x in model.run().records}
    assert [times(r[t], "weigh_in")[0] for t in ("T1", "T2", "T3")] == [hm("07:00"), hm("07:00"), hm("07:02")]


# Head-of-line case: WBI weighs in only, WBO weighs out only, 2 min each.
#   A (unload: weigh_in, weigh_out) arrives 07:00 -> on WBI 07:00-07:02.
#   B (unload) arrives 07:01 -> needs WBI, busy until 07:02.
#   C (load: weigh_out only) arrives 07:01:30 -> WBO is free.
HOL_SITE = site([wb("WBI", moves="in"), wb("WBO", moves="out")],
                {"unload": ["weigh_in", "weigh_out"], "load": ["weigh_out"]})
HOL_TRUCKS = trucks(("A", "unload", "07:00"), ("B", "unload", "07:01"), ("C", "load", "07:01:30"))


def test_feasible_first_lets_a_later_truck_use_a_free_weighbridge():
    """C overtakes the blocked B: C on WBO 07:01:30-07:03:30.
    07:02: A leaves WBI; B starts WBI 07:02-07:04; A waits for WBO until 07:03:30, out 07:03:30-07:05:30.
    07:04: B needs WBO, busy with A until 07:05:30; B out 07:05:30-07:07:30.
    B was overtaken once (by C)."""
    result = TruckFlowModel(HOL_SITE, HOL_TRUCKS, TWO_MIN, policy="feasible_first").run()
    r = {x.truck_id: x for x in result.records}
    assert times(r["C"], "weigh_out") == (hm("07:01:30"), hm("07:03:30"))
    assert times(r["A"], "weigh_out") == (hm("07:03:30"), hm("07:05:30"))
    assert times(r["B"], "weigh_in") == (hm("07:02"), hm("07:04"))
    assert times(r["B"], "weigh_out") == (hm("07:05:30"), hm("07:07:30"))
    assert result.overtaken == {"B/weigh_in": 1}


def test_strict_fifo_holds_the_later_truck_behind_the_blocked_one():
    """C may not start before B (same weighing queue), although WBO is free.
    07:02: B starts WBI 07:02-07:04, then C starts WBO 07:02-07:04; A's weigh-out (queued 07:02) waits.
    07:04: B's weigh-in ends first (scheduled first) but WBO is still busy at that instant; then C leaves WBO
    and A, queued earlier than B's weigh-out, gets WBO 07:04-07:06; B out 07:06-07:08."""
    result = TruckFlowModel(HOL_SITE, HOL_TRUCKS, TWO_MIN, policy="strict_fifo").run()
    r = {x.truck_id: x for x in result.records}
    assert times(r["C"], "weigh_out") == (hm("07:02"), hm("07:04"))
    assert times(r["A"], "weigh_out") == (hm("07:04"), hm("07:06"))
    assert times(r["B"], "weigh_out") == (hm("07:06"), hm("07:08"))
    assert result.overtaken == {}


def test_waiting_reasons_explain_why_each_truck_is_waiting():
    """At 07:01:30 under strict FIFO: B waits for busy weigh-in equipment; C waits behind B."""
    model = TruckFlowModel(HOL_SITE, HOL_TRUCKS, TWO_MIN, policy="strict_fifo")
    model.run(until=hm("07:01:30"))
    reasons = {rid: [r.code for r in rs] for rid, rs in model.waiting_reasons().items()}
    assert reasons == {"B/weigh_in": ["EQUIPMENT_BUSY"], "C/weigh_out": ["QUEUE_ORDER"]}


def test_samples_return_out_of_order_and_each_truck_waits_for_its_own_result():
    """Sampler 1 lane (2 min), grading lab 2 lanes, weighbridge 1 lane (2 min).
    Grading takes 10 min for T1's sample and 3 min for T2's.
    T1: sampled 07:00-07:02; sample graded 07:02-07:12; T1 waits at grading 10 min; weigh-in 07:12-07:14.
    T2: arrives 07:01, sampled 07:02-07:04; graded 07:04-07:07; waits 3 min; weigh-in 07:07-07:09.
    T2 leaves before T1, and T2's result never releases T1."""
    s = site([{"id": "S1", "type": "sampler", "name": "Sampler", "cap": 1, "time": [2, 2, 2]},
              {"id": "G1", "type": "grader", "name": "Lab", "cap": 2, "time": [3, 3, 3]},
              wb("WB1")],
             {"unload": ["sample", "grade", "weigh_in"]})
    t = FixedServiceTimes({"sample": 2, "grade": 3, "weigh_in": 2}, overrides={("T1", "grade"): 10})
    result = TruckFlowModel(s, trucks(("T1", "unload", "07:00"), ("T2", "unload", "07:01")), t,
                            policy="feasible_first").run()
    r = {x.truck_id: x for x in result.records}
    t1_grade, t2_grade = (next(x for x in r[k].steps if x.step == "grade") for k in ("T1", "T2"))
    assert (t1_grade.entered, t1_grade.finished) == (hm("07:02"), hm("07:12"))
    assert (t2_grade.entered, t2_grade.finished) == (hm("07:04"), hm("07:07"))
    assert times(r["T2"], "weigh_in") == (hm("07:07"), hm("07:09"))
    assert times(r["T1"], "weigh_in") == (hm("07:12"), hm("07:14"))
    assert r["T2"].departed < r["T1"].departed
    assert result.samples == {"S-T1": ("T1", hm("07:12")), "S-T2": ("T2", hm("07:07"))}


def test_another_trucks_result_already_back_does_not_release_a_truck():
    """T1's sample is graded in 1 min, T2's in 10 min. Sampler 1 lane (2 min), lab 2 lanes, weighbridge 2 min.
    T1: sampled 07:00-07:02, graded 07:02-07:03, weigh-in 07:03-07:05.
    T2: arrives 07:01, sampled 07:02-07:04. At 07:04 T2 reaches grading while T1's result is already back;
    T2 must still wait for its own: graded 07:04-07:14, weigh-in 07:14-07:16."""
    s = site([{"id": "S1", "type": "sampler", "name": "Sampler", "cap": 1, "time": [2, 2, 2]},
              {"id": "G1", "type": "grader", "name": "Lab", "cap": 2, "time": [3, 3, 3]},
              wb("WB1")],
             {"unload": ["sample", "grade", "weigh_in"]})
    t = FixedServiceTimes({"sample": 2, "grade": 3, "weigh_in": 2},
                          overrides={("T1", "grade"): 1, ("T2", "grade"): 10})
    result = TruckFlowModel(s, trucks(("T1", "unload", "07:00"), ("T2", "unload", "07:01")), t,
                            policy="feasible_first").run()
    r = {x.truck_id: x for x in result.records}
    t2_grade = next(x for x in r["T2"].steps if x.step == "grade")
    assert (t2_grade.entered, t2_grade.finished) == (hm("07:04"), hm("07:14"))
    assert times(r["T1"], "weigh_in") == (hm("07:03"), hm("07:05"))
    assert times(r["T2"], "weigh_in") == (hm("07:14"), hm("07:16"))


def test_trucks_still_on_site_when_the_run_stops_are_reported_not_dropped():
    """Same as the first test, stopped at 07:05: T3 is on the weighbridge (since 07:04), on site since 07:01."""
    model = TruckFlowModel(site([wb("WB1")], {"weigh": ["weigh_in"]}),
                           trucks(("T1", "weigh", "07:00"), ("T2", "weigh", "07:01"), ("T3", "weigh", "07:01")),
                           TWO_MIN, policy="feasible_first")
    result = model.run(until=hm("07:05"))
    assert [(u.truck_id, u.step, u.in_service, u.arrived, u.step_entered) for u in result.unfinished] == [
        ("T3", "weigh_in", True, hm("07:01"), hm("07:01"))]
    assert [x.truck_id for x in result.records if x.departed is not None] == ["T1", "T2"]


def test_identical_inputs_give_identical_results():
    def run():
        res = TruckFlowModel(HOL_SITE, HOL_TRUCKS, TWO_MIN, policy="feasible_first").run()
        return [(r.truck_id, r.departed, [(s.step, s.unit, s.entered, s.started, s.finished) for s in r.steps])
                for r in res.records], [(e.time, e.priority, e.seq, e.label) for e in res.trace]
    assert run() == run()


def test_steps_not_built_yet_are_refused_explicitly():
    s = site([wb("WB1")], {"unload": ["weigh_in", "tip", "weigh_out"]})
    with pytest.raises(NotYetSupported, match="tip"):
        TruckFlowModel(s, trucks(("T1", "unload", "07:00")), TWO_MIN, policy="feasible_first")


def test_missing_station_or_grading_without_sampling_is_a_model_error():
    with pytest.raises(ModelError, match="sampler"):
        TruckFlowModel(site([wb("WB1")], {"unload": ["sample", "weigh_in"]}),
                       trucks(("T1", "unload", "07:00")), TWO_MIN, policy="feasible_first")
    grader = {"id": "G1", "type": "grader", "name": "Lab", "cap": 1, "time": [3, 3, 3]}
    with pytest.raises(ModelError, match="sample"):
        TruckFlowModel(site([grader, wb("WB1")], {"unload": ["grade", "weigh_in"]}),
                       trucks(("T1", "unload", "07:00")), TWO_MIN, policy="feasible_first")
    with pytest.raises(ModelError, match="weighs out"):
        TruckFlowModel(site([wb("WBI", moves="in")], {"unload": ["weigh_in", "weigh_out"]}),
                       trucks(("T1", "unload", "07:00")), TWO_MIN, policy="feasible_first")


def test_unknown_policy_is_refused():
    with pytest.raises(ModelError, match="policy"):
        TruckFlowModel(HOL_SITE, HOL_TRUCKS, TWO_MIN, policy="random")
