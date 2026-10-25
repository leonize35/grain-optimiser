"""Grading while the truck moves on, and a truck waiting for its result blocking the incoming weighbridge
(confirmed Ventersdorp receiving rule, 2026-10-25). Hand-traced.

Rule: after sampling the truck leaves the sampler (the sampler is free when sampling is complete) and goes to the
incoming weighbridge queue. If the bridge is free it drives on and is weighed even if its grading result is pending;
it then stays on the bridge until the result is available, and only then goes on to a hopper. While it waits there
no other truck can use that bridge. Represented by the receiving sequence sample -> weigh_in -> grade -> tip ->
weigh_out, where `grade` after `weigh_in` means "hold the current place (the bridge) until the result exists".
Weighing itself does not wait for grading.

Site (test inputs, not Ventersdorp data): sampler S1 (one truck, 4 min); grader G1 (one sample at a time, 10 min,
longer than the truck takes to reach and cross the bridge); incoming bridge WB_IN and outgoing WB_OUT (one truck
each, 2 min); one hopper (tip 5 min, drains 1 800 t/h). No travel times between stations.
"""
import copy

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import TruckFlowModel

RAW = {
    "id": "grading", "name": "Grading test site", "version": 1, "hours": {"open": 7, "close": 18},
    "commodities": [{"id": "YM", "name": "Yellow maize"}],
    "equipment": [
        {"id": "S1", "type": "sampler", "name": "Sampler", "cap": 1, "time": [4, 4, 4]},
        {"id": "G1", "type": "grader", "name": "Grader", "cap": 1, "time": [10, 10, 10]},
        {"id": "WB_IN", "type": "weighbridge", "name": "Incoming", "cap": 1, "moves": "in", "time": [2, 2, 2]},
        {"id": "WB_OUT", "type": "weighbridge", "name": "Outgoing", "cap": 1, "moves": "out", "time": [2, 2, 2]},
        {"id": "H1", "type": "hopper", "name": "H1", "capT": 60, "rate": 1800, "tip": [5, 5, 5], "commodities": ["YM"]},
        {"id": "C1", "type": "conveyor", "name": "C1", "rate": 1800},
        {"id": "E1", "type": "elevator", "name": "E1", "rate": 1800},
        {"id": "B1", "type": "bin", "name": "B1", "capT": 5000, "commodities": ["YM"]}],
    "edges": [["H1", "C1"], ["C1", "E1"], ["E1", "B1"]],
    "sequences": {"unload": ["sample", "weigh_in", "grade", "tip", "weigh_out"]},
    "demand": {}, "changeovers": {"default_minutes": 0}}
# The rule needs an explicit truck path with no waiting area between weigh_in and grade (without a configured path
# the engine puts an unlimited implicit area before every step, so the truck would leave the bridge). Queue areas
# before the hopper and the outgoing bridge are unlimited here; real capacities are question Q-4.
PATH = ["sample", "wb_queue", "weigh_in", "grade", "hopper_queue", "tip", "out_queue", "weigh_out"]


def paths(wb_queue=None):
    return {"truck_areas": [{"id": "wb_queue", "name": "Weighbridge queue", "capacity": wb_queue},
                            {"id": "hopper_queue", "name": "Hopper queue"}, {"id": "out_queue", "name": "Exit queue"}],
            "truck_paths": {"unload": PATH}}


WITH_QUEUE = paths(wb_queue=1)  # one queue place between the sampler and the incoming bridge


def run(trucks, grade_min=10, **extra):
    raw = copy.deepcopy(RAW)
    raw.update(copy.deepcopy(extra))
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": 30} for t, at in trucks]})
    times = FixedServiceTimes({"sample": 4, "grade": grade_min, "weigh_in": 2, "tip": 5, "weigh_out": 2})
    r = TruckFlowModel(s, script, times, policy="feasible_first").run()
    audit = audit_flow(s, script, r)
    assert r.violations == [] and r.material_balance_kg == 0 and r.stall is None
    assert audit.ok, audit.problems
    return r


def step(r, truck, name):
    rec = next(x for x in r.records if x.truck_id == truck)
    return next(s for s in rec.steps if s.step == name)


def bridge_occupancy(r):
    """(truck, on, off) for the incoming bridge: from driving on (weigh-in start) to leaving it."""
    out = []
    for rec in r.records:
        s = next((s for s in rec.steps if s.step == "weigh_in"), None)
        if s is not None and s.started is not None:
            out.append((rec.truck_id, s.started, s.left))
    return sorted(out, key=lambda x: x[1])


def test_truck_waiting_for_grading_holds_the_incoming_weighbridge():
    """T1 07:00, T2 07:01, T3 07:02; no queue limits.
    T1: sampled 07:00-07:04; its sample is graded 07:04-07:14 while T1 drives onto WB_IN at 07:04, is weighed
        07:04-07:06 and stays on the bridge until its result at 07:14; tips 07:14-07:19, WB_OUT 07:19-07:21.
    T2: sampled 07:04-07:08 (the sampler is free once T1's sampling is done); graded 07:14-07:24 (grader busy);
        WB_IN is held by T1 until 07:14: T2 weighs 07:14-07:16 and holds the bridge until 07:24.
    T3: sampled 07:08-07:12; graded 07:24-07:34; on WB_IN 07:24-07:34 (weighed 07:24-07:26).
    The bridge is never used by two trucks at once and is occupied back to back by trucks waiting for results."""
    r = run([("T1", "07:00"), ("T2", "07:01"), ("T3", "07:02")], **paths())
    assert [(step(r, t, "sample").started, step(r, t, "sample").finished) for t in ("T1", "T2", "T3")] == [
        (hm("07:00"), hm("07:04")), (hm("07:04"), hm("07:08")), (hm("07:08"), hm("07:12"))]
    assert bridge_occupancy(r) == [("T1", hm("07:04"), hm("07:14")), ("T2", hm("07:14"), hm("07:24")),
                                   ("T3", hm("07:24"), hm("07:34"))]
    t1 = step(r, "T1", "weigh_in")
    assert (t1.started, t1.finished) == (hm("07:04"), hm("07:06"))  # weighing did not wait for the result
    assert r.samples["S-T1"] == ("T1", hm("07:14"))  # result time
    assert step(r, "T1", "tip").started == hm("07:14")  # no hopper before the result
    occ = bridge_occupancy(r)
    assert all(a[2] <= b[1] for a, b in zip(occ, occ[1:]))  # never two trucks on the bridge


def test_without_a_truck_path_the_truck_does_not_wait_on_the_bridge():
    """Default (no configured path): an implicit unlimited area before `grade` lets T1 leave WB_IN at 07:06. This is
    why the Ventersdorp configuration must give the receiving path explicitly."""
    r = run([("T1", "07:00"), ("T2", "07:01"), ("T3", "07:02")])
    assert bridge_occupancy(r)[0] == ("T1", hm("07:04"), hm("07:06"))


def test_fast_grading_releases_the_bridge_after_weighing():
    """Grading 1 min: T1's result is ready at 07:05, before weighing ends, so T1 leaves WB_IN at 07:06."""
    r = run([("T1", "07:00"), ("T2", "07:01"), ("T3", "07:02")], grade_min=1, **paths())
    assert bridge_occupancy(r)[0] == ("T1", hm("07:04"), hm("07:06"))


def test_grading_delay_propagates_upstream_to_the_sampler():
    """With one queue place before the bridge (and reserve_next_space: sampling starts only with that place reserved):
    T1 sampled 07:00-07:04, through the queue onto WB_IN at 07:04, held there until 07:14.
    T2 sampled 07:04-07:08, then waits in the queue place (WB_IN held by T1).
    T3 cannot start sampling at 07:08: the queue place is taken. It starts when T2 moves onto WB_IN at 07:14.
    With 1-minute grading T3 starts sampling at 07:08. The grading delay reaches back to the sampler."""
    trucks = [("T1", "07:00"), ("T2", "07:01"), ("T3", "07:02")]
    slow = run(trucks, **WITH_QUEUE)
    assert bridge_occupancy(slow)[:2] == [("T1", hm("07:04"), hm("07:14")), ("T2", hm("07:14"), hm("07:24"))]
    assert step(slow, "T3", "sample").started == hm("07:14")
    assert slow.area_peak["wb_queue"] == 1
    fast = run(trucks, grade_min=1, **WITH_QUEUE)
    assert step(fast, "T3", "sample").started == hm("07:08")
    w = slow.truck_metrics["T3"].total_waiting_min - fast.truck_metrics["T3"].total_waiting_min
    assert w > 0
