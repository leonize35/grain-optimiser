"""Sampler access, physical queue blocking and sampler location (docs/SAMPLER_ACCESS_DESIGN.md §5): the four
hand-traced acceptance cases S1-S4, plus the separation of (1) the sampling requirement, (2) the physical layout
(single-file queues, declared bypasses) and (3) where sampling happens.

Shared resources in every case: one sampling unit, two weighbridge bays (WB1#0, WB1#1). Sampling 4 min, weighing
2 min, drive-through of an unsampled truck through a sampler bay 0.5 min, no travel time. Trucks arrive in script
order T1 (sampled), T4 (sampled), T2 (not sampled) at 07:00 and T3 (not sampled) at 07:01. Unloading = sample,
weigh_in (no grading, no tipping), so a truck's weigh-in end is its departure.
"""
import copy

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel
from test_starvation_diagnostics import ONE_HOPPER

TIMES = FixedServiceTimes({"sample": 4, "weigh_in": 2, "pass": 0.5})
TRUCKS = [("T1", "07:00", True), ("T4", "07:00", True), ("T2", "07:00", False), ("T3", "07:01", False)]
SAMPLER = {"id": "S1", "type": "sampler", "name": "Sampler", "cap": 1, "time": [4, 4, 4], "pass_through": [0.5, 0.5, 0.5]}
WEIGHBRIDGE = {"id": "WB1", "type": "weighbridge", "name": "Weighbridge", "cap": 2, "time": [2, 2, 2]}
AREAS = [{"id": "gate", "name": "Gate", "capacity": None},
         {"id": "approach", "name": "Sampler approach", "capacity": None, "single_file": True},
         {"id": "holding", "name": "Holding space", "capacity": 1}]


def site(layout: str, holding: bool = True, bypass: bool = False, bypass_to: str = "weigh_in"):
    raw = copy.deepcopy(ONE_HOPPER)
    sampler = dict(SAMPLER)
    raw["sequences"] = {"unload": ["sample", "weigh_in"]}
    if layout == "separate":
        raw["truck_areas"] = AREAS if holding else AREAS[:2]
        raw["truck_paths"] = {"unload": ["gate", "approach", "sample"] + (["holding"] if holding else []) + ["weigh_in"]}
        if bypass:
            raw["truck_bypasses"] = [{"activity": "unload", "from": "gate", "to": bypass_to, "for": "not_sampled"}]
    else:  # sampling at the weighbridge: probe at bay 0
        sampler.update({"located_at": "WB1", "located_lanes": [0]})
        raw["truck_areas"] = AREAS[:2]
        raw["truck_paths"] = {"unload": ["gate", "approach", "sample", "weigh_in"]}
        if bypass:
            raw["truck_bypasses"] = [{"activity": "unload", "from": "approach", "to": "weigh_in", "for": "not_sampled"}]
    raw["equipment"] = raw["equipment"] + [sampler, WEIGHBRIDGE]
    return raw


def run(raw, policy="feasible_first", trucks=TRUCKS):
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": 30, "requires_sampling": req}
        for t, at, req in trucks]})
    r = TruckFlowModel(s, script, TIMES, policy=policy).run()
    audit = audit_flow(s, script, r)
    assert r.violations == [] and r.material_balance_kg == 0 and r.stall is None
    assert audit.ok, audit.problems
    return r


def step(r, truck, name):
    rec = next(x for x in r.records if x.truck_id == truck)
    return next((s for s in rec.steps if s.step == name), None)


def weigh(r):
    return {t: (step(r, t, "weigh_in").started, step(r, t, "weigh_in").finished, step(r, t, "weigh_in").unit)
            for t, _, _ in TRUCKS}


def m(clock):
    return hm(clock[:5]) + (30_000 if clock.endswith(":30") and len(clock) == 8 else 0)


# ---- S1: separate upstream sampler, no bypass, holding space for 1 truck ----

def test_s1_unsampled_trucks_are_blocked_and_pass_through_without_sampling():
    r = run(site("separate"))
    assert weigh(r) == {"T1": (hm("07:04"), hm("07:06"), "WB1#0"), "T4": (hm("07:08"), hm("07:10"), "WB1#0"),
                        "T2": (m("07:08:30"), m("07:10:30"), "WB1#1"), "T3": (hm("07:10"), hm("07:12"), "WB1#0")}
    assert [t for t, *_ in TRUCKS if step(r, t, "sample")] == ["T1", "T4"]  # only sampled trucks get sampling service
    p2, p3 = step(r, "T2", "pass"), step(r, "T3", "pass")
    assert (p2.unit, p2.started, p2.finished) == ("S1#0", hm("07:08"), m("07:08:30"))
    assert (p3.unit, p3.started, p3.finished) == ("S1#0", m("07:08:30"), hm("07:09"))
    a = r.truck_access
    assert (a["T2"]["blocked_behind_ms"], a["T3"]["blocked_behind_ms"]) == (4 * 60_000, 7 * 60_000)
    assert (a["T2"]["pass_throughs"], a["T1"]["pass_throughs"], a["T2"]["requires_sampling"]) == (1, 0, False)


def test_s1_without_holding_space_an_unsampled_truck_blocks_the_sampler_bay():
    """No holding area: T3 passes through 07:08:30-07:09 and stays in the sampler bay until bay 0 frees at 07:10."""
    r = run(site("separate", holding=False))
    p3 = step(r, "T3", "pass")
    assert (p3.finished, p3.left) == (hm("07:09"), hm("07:10"))
    assert step(r, "T3", "weigh_in").started == hm("07:10")


# ---- S2: separate upstream sampler, bypass from the gate ----

def test_s2_bypass_lets_unsampled_trucks_skip_the_approach_and_the_sampler():
    r = run(site("separate", bypass=True))
    assert weigh(r) == {"T2": (hm("07:00"), hm("07:02"), "WB1#0"), "T3": (hm("07:01"), hm("07:03"), "WB1#1"),
                        "T1": (hm("07:04"), hm("07:06"), "WB1#0"), "T4": (hm("07:08"), hm("07:10"), "WB1#0")}
    assert step(r, "T2", "pass") is None and step(r, "T2", "sample") is None
    a = r.truck_access
    assert (a["T2"]["bypass_used"], a["T1"]["bypass_used"]) == (True, False)  # sampled trucks never take it
    assert a["T2"]["blocked_behind_ms"] == a["T3"]["blocked_behind_ms"] == 0


def test_a_bypass_into_a_promised_holding_place_gives_no_benefit():
    """Variant of S2 whose bypass joins the holding area (1 place) instead of the weighbridge. Under
    reserve_next_space the truck being sampled holds the promise of that place (T1 07:00-07:04, T4 07:04-07:08),
    so T2 can enter it only at 07:08 (weighs at bay 1, 07:08-07:10); T3 follows into it and weighs at bay 0
    07:10-07:12. Unsampled trucks never enter the sampler bay, but gain nothing."""
    r = run(site("separate", bypass=True, bypass_to="holding"))
    assert weigh(r) == {"T1": (hm("07:04"), hm("07:06"), "WB1#0"), "T4": (hm("07:08"), hm("07:10"), "WB1#0"),
                        "T2": (hm("07:08"), hm("07:10"), "WB1#1"), "T3": (hm("07:10"), hm("07:12"), "WB1#0")}
    assert step(r, "T2", "pass") is None and r.truck_access["T2"]["bypass_used"]


# ---- S3: sampling at the weighbridge (probe at bay 0), single-file approach, no bypass ----

def test_s3_colocated_sampling_reserves_the_bay_and_blocks_trucks_behind():
    r = run(site("colocated"))
    assert weigh(r) == {"T1": (hm("07:04"), hm("07:06"), "WB1#0"), "T4": (hm("07:10"), hm("07:12"), "WB1#0"),
                        "T2": (hm("07:06"), hm("07:08"), "WB1#1"), "T3": (hm("07:08"), hm("07:10"), "WB1#1")}
    s1, s4 = step(r, "T1", "sample"), step(r, "T4", "sample")
    assert (s1.unit, s1.started, s1.finished, s1.left) == ("WB1#0", hm("07:00"), hm("07:04"), hm("07:04"))
    assert (s4.unit, s4.started, s4.finished) == ("WB1#0", hm("07:06"), hm("07:10"))
    assert step(r, "T2", "pass") is None and step(r, "T2", "sample") is None
    a = r.truck_access
    assert (a["T2"]["blocked_behind_ms"], a["T3"]["blocked_behind_ms"]) == (6 * 60_000, 5 * 60_000)


# ---- S4: sampling at the weighbridge, unsampled trucks may pass a waiting sampled truck ----

def test_s4_bypass_lets_unsampled_trucks_use_the_bay_without_a_probe():
    r = run(site("colocated", bypass=True))
    assert weigh(r) == {"T2": (hm("07:00"), hm("07:02"), "WB1#1"), "T3": (hm("07:02"), hm("07:04"), "WB1#1"),
                        "T1": (hm("07:04"), hm("07:06"), "WB1#0"), "T4": (hm("07:10"), hm("07:12"), "WB1#0")}
    assert r.truck_access["T2"]["blocked_behind_ms"] == r.truck_access["T3"]["blocked_behind_ms"] == 0


# ---- separation of concepts ----

def test_a_queue_policy_cannot_create_a_bypass():
    for policy in ("feasible_first", "strict_fifo"):
        r = run(site("separate"), policy=policy)
        assert step(r, "T2", "pass").started == hm("07:08")  # still behind T4, whatever the policy


def test_sampling_requirement_is_independent_of_the_layout():
    """With every truck requiring sampling, the S2 bypass is never used and all four are sampled."""
    trucks = [(t, at, True) for t, at, _ in TRUCKS]
    r = run(site("separate", bypass=True), trucks=trucks)
    assert all(step(r, t, "sample") for t, *_ in trucks)
    assert not any(r.truck_access[t]["bypass_used"] for t, *_ in trucks)


def test_default_requirement_follows_the_sequence_and_old_configs_are_unchanged():
    raw = site("separate")
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [{"id": "X", "activity": "unload", "arrive": "07:00", "commodity": "YM", "tonnes": 30}]})
    r = TruckFlowModel(s, script, TIMES, policy="feasible_first").run()
    assert step(r, "X", "sample") is not None and r.truck_access["X"]["requires_sampling"] is True


def test_area_occupancy_is_reported_time_weighted():
    r = run(site("separate"))
    occ = r.area_occupancy
    assert occ["approach"]["peak"] == 3 and occ["holding"]["peak"] == 1 and occ["approach"]["single_file"] is True
    assert occ["approach"]["time_average"] > 0


@pytest.mark.parametrize("change, words", [
    (lambda raw: raw.update(truck_bypasses=[{"activity": "unload", "from": "nowhere", "to": "holding", "for": "not_sampled"}]), "bypass"),
    (lambda raw: raw.update(truck_bypasses=[{"activity": "unload", "from": "holding", "to": "gate", "for": "not_sampled"}]), "bypass"),
    (lambda raw: raw["equipment"][-2].update(located_at="NOPE"), "located_at"),
    (lambda raw: raw["equipment"][-2].update(located_at="WB1", located_lanes=[5]), "lane"),
])
def test_invalid_access_layouts_are_refused(change, words):
    raw = site("separate")
    change(raw)
    with pytest.raises(ModelError) as err:
        run(raw)
    assert words in str(err.value)


# ---- the independent audit checks the access rules ----

def _corrupt_and_audit(layout, fn, **kw):
    raw = site(layout, **kw)
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": 30, "requires_sampling": req}
        for t, at, req in TRUCKS]})
    r = TruckFlowModel(s, script, TIMES, policy="feasible_first").run()
    bad = copy.deepcopy(r)
    fn(bad)
    return audit_flow(s, script, bad).problems


def _swap_exits(r, a, b):
    """Swap the single-file exits of trucks a and b (b now leaves while a is still in front of it)."""
    log = r.single_file_log
    i = next(k for k, e in enumerate(log) if e[2] == a and e[3] == "exit")
    j = next(k for k, e in enumerate(log) if e[2] == b and e[3] == "exit")
    log[i], log[j] = (log[j][0], *log[i][1:]), (log[i][0], *log[j][1:])
    log[i], log[j] = log[j], log[i]


def _rec(r, t):
    return next(x for x in r.records if x.truck_id == t)


@pytest.mark.parametrize("layout, fn, words", [
    ("separate", lambda r: setattr(next(s for s in _rec(r, "T2").steps if s.step == "pass"), "step", "sample"), "needs no sampling"),
    ("separate", lambda r: setattr(next(s for s in _rec(r, "T3").steps if s.step == "weigh_in"), "unit", "WB1#1"), "occupy it together"),
    ("separate", lambda r: _swap_exits(r, "T4", "T2"), "from behind"),
    ("colocated", lambda r: setattr(next(s for s in _rec(r, "T4").steps if s.step == "sample"), "started", hm("07:02")), "sampling unit"),
])
def test_audit_detects_access_violations(layout, fn, words):
    problems = _corrupt_and_audit(layout, fn)
    assert any(words in p for p in problems), problems
