"""Shared unloading workers across two silos (docs/OPERATOR_STAFFING_DESIGN.md §11). Hand-traced.

The pools, task lists, worker counts and times here are TEST INPUTS, not facts about Ventersdorp (all unverified).

Site: Silo A (hopper HA -> CA -> EA -> bin BA) and Silo B (HB -> CB -> EB -> BB), no shared grain equipment; both take
yellow maize. Hoppers hold 60 t; trucks carry 30 t; elevators 200 t/h. Unload sequence: tip only (no truck path).
Hopper candidates are tried in configuration order (HA before HB).
Unloading tasks (default): position 1 worker 2 min -> discharge (the hopper's tipping time, 5 min) 0 workers ->
scrape 1 worker 3 min.
"""
import copy

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes, StochasticServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel

TIMES = FixedServiceTimes({"tip": 5, "tip:position": 2, "tip:scrape": 3, "tip:sweep": 4})


def hopper(hid):
    return {"id": hid, "type": "hopper", "name": hid, "capT": 60, "rate": 400, "tip": [5, 5, 5], "commodities": ["YM"]}


def line(s):
    return [{"id": f"C{s}", "type": "conveyor", "name": f"C{s}", "rate": 300},
            {"id": f"E{s}", "type": "elevator", "name": f"E{s}", "rate": 200},
            {"id": f"B{s}", "type": "bin", "name": f"B{s}", "capT": 1000, "commodities": ["YM"]}]


def task(tid, workers, time, present=True):
    return {"id": tid, "operators": workers, "time": time, "truck_present": present}


DEFAULT_TASKS = [task("position", 1, [2, 2, 2]), task("discharge", 0, "tip"), task("scrape", 1, [3, 3, 3])]


def site(workers=1, tasks=DEFAULT_TASKS, allocation="oldest_task_first", **extra):
    raw = {"id": "two-silo", "name": "Two-silo test site", "version": 1, "hours": {"open": 7, "close": 18},
           "commodities": [{"id": "YM", "name": "Yellow maize"}],
           "equipment": [hopper("HA"), hopper("HB")] + line("A") + line("B"),
           "edges": [["HA", "CA"], ["CA", "EA"], ["EA", "BA"], ["HB", "CB"], ["CB", "EB"], ["EB", "BB"]],
           "sequences": {"unload": ["tip"]}, "demand": {}, "changeovers": {"default_minutes": 0},
           "operator_pools": [{"id": "unloaders", "skills": ["tip"], "verified": False,
                               "schedule": [{"from": "07:00", "to": "18:00", "count": workers}]}],
           "unloading_labour": {"pool": "unloaders", "tasks": copy.deepcopy(tasks), "allocation": allocation}}
    raw.update(extra)
    return raw


def run(raw, trucks, staffing=None, times=TIMES):
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": 30} for t, at in trucks]})
    r = TruckFlowModel(s, script, times, policy="feasible_first", staffing=staffing).run()
    audit = audit_flow(s, script, r)
    assert r.violations == [] and r.material_balance_kg == 0 and r.stall is None
    assert audit.ok, audit.problems
    return r


def tasks_of(r):
    """(owner, task, start, end) per worker use, in start order."""
    return sorted((u["owner"], u["step"], u["start"], u["end"]) for u in r.labour_use)


def tip_times(r):
    return {x.truck_id: next((s.unit, s.started, s.finished) for s in x.steps if s.step == "tip") for x in r.records}


def test_two_workers_serve_both_silos_at_once():
    """2 workers. T1 (HA) and T2 (HB) both position 07:00-07:02 (one worker each), discharge 07:02-07:07 without
    workers. At 07:07 both need a scraper: one worker each, 07:07-07:10."""
    r = run(site(workers=2), [("T1", "07:00"), ("T2", "07:00")])
    assert tip_times(r) == {"T1": ("HA", hm("07:00"), hm("07:10")), "T2": ("HB", hm("07:00"), hm("07:10"))}
    assert r.staffing["pools"]["unloaders"]["busy_operator_minutes"] == 2 * (2 + 3)


def test_one_worker_cannot_do_two_tasks():
    """1 worker. 07:00 T1 positions at HA; HB is free but T2 waits for the worker. 07:02 T1 discharges (no worker),
    T2 positions at HB 07:02-07:04 and discharges 07:04-07:09. 07:07 T1 scrapes 07:07-07:10. 07:09 T2 needs the
    worker, busy until 07:10: T2 scrapes 07:10-07:13. The worker moves between the silos as needed."""
    r = run(site(workers=1), [("T1", "07:00"), ("T2", "07:00")])
    assert tip_times(r) == {"T1": ("HA", hm("07:00"), hm("07:10")), "T2": ("HB", hm("07:02"), hm("07:13"))}
    assert tasks_of(r) == [
        ("T1/tip#0", "tip:position", hm("07:00"), hm("07:02")), ("T1/tip#2", "tip:scrape", hm("07:07"), hm("07:10")),
        ("T2/tip#0", "tip:position", hm("07:02"), hm("07:04")), ("T2/tip#2", "tip:scrape", hm("07:10"), hm("07:13"))]
    w = r.waiting_attribution  # truck-minutes: T2 waits 2 min to position and, on the hopper, 1 min for a scraper
    assert w["LABOUR_UNAVAILABLE:unloaders"] == 3.0


@pytest.mark.parametrize("allocation, t2_scrape, t3_position", [
    ("oldest_task_first", ("07:12", "07:15"), ("07:10", "07:12")),
    ("started_trucks_first", ("07:10", "07:13"), ("07:13", "07:15")),
])
def test_allocation_rule_is_configurable(allocation, t2_scrape, t3_position):
    """1 worker, 3 trucks at 07:00. T1 positions HA 07:00-07:02; T2 positions HB 07:02-07:04; T1 scrapes 07:07-07:10;
    T2 asks to scrape at 07:09. At 07:10 HA is free: T3's start (waiting since 07:00) and T2's scrape (since 07:09)
    compete for the worker. Oldest task first: T3 first. Started trucks first: T2 first."""
    r = run(site(workers=1, allocation=allocation), [("T1", "07:00"), ("T2", "07:00"), ("T3", "07:00")])
    use = {(o.split("/")[0], step): (s, e) for o, step, s, e in tasks_of(r)}
    assert use[("T2", "tip:scrape")] == tuple(hm(t) for t in t2_scrape)
    assert use[("T3", "tip:position")] == tuple(hm(t) for t in t3_position)


def test_cleaning_after_the_truck_occupies_workers_not_the_hopper():
    """Tasks: position 1w 2 min, discharge 5 min, sweep after the truck 1w 4 min. T1 at HA 07:00-07:07, then the sweep
    07:07-07:11. T2 arrives 07:08. With 1 worker T2 waits for the sweeper (positions 07:11); with 2 workers T2 takes
    HA at once (07:08) while the sweep goes on: the sweep does not hold the hopper (provisional, Q-3)."""
    tasks = [task("position", 1, [2, 2, 2]), task("discharge", 0, "tip"), task("sweep", 1, [4, 4, 4], present=False)]
    trucks = [("T1", "07:00"), ("T2", "07:08")]
    one = run(site(workers=1, tasks=tasks), trucks)
    assert tip_times(one)["T2"] == ("HA", hm("07:11"), hm("07:18"))
    assert ("HA/after#1#2", "tip:sweep", hm("07:07"), hm("07:11")) in tasks_of(one)
    two = run(site(workers=2, tasks=tasks), trucks)
    assert tip_times(two)["T2"] == ("HA", hm("07:08"), hm("07:15"))


def test_workforce_per_period_is_a_staffing_scenario():
    """Normal 1 worker (baseline); busy 2. With 2 workers T2 positions at 07:00 instead of 07:02. Equipment unchanged."""
    raw = site(workers=1, staffing_scenarios={
        "busy": {"pools": {"unloaders": [{"from": "07:00", "to": "18:00", "count": 2}]}},
        "peak": {"pools": {"unloaders": [{"from": "07:00", "to": "18:00", "count": 4}]}}})
    trucks = [("T1", "07:00"), ("T2", "07:00")]
    assert tip_times(run(raw, trucks))["T2"][1] == hm("07:02")
    busy = run(raw, trucks, staffing="busy")
    assert tip_times(busy)["T2"][1] == hm("07:00")
    assert busy.staffing["scenario"] == "busy" and busy.staffing["pools"]["unloaders"]["available_operator_minutes"] == 2 * 660


def test_a_scenario_can_change_the_workers_a_task_needs():
    """Scraping by 2 workers (scenario) with 2 workers in the pool: T2's scrape waits for both; baseline (1) does not."""
    raw = site(workers=2, staffing_scenarios={"two_scrapers": {"labour": {"tip:scrape": 2}}})
    trucks = [("T1", "07:00"), ("T2", "07:00")]
    assert tip_times(run(raw, trucks))["T2"][2] == hm("07:10")
    r = run(raw, trucks, staffing="two_scrapers")
    assert tip_times(r)["T2"][2] == hm("07:13")
    assert r.staffing["unloading_tasks"]["tasks"][2] == {"id": "scrape", "workers": 2, "truck_present": True}


def test_stochastic_task_times_leave_the_discharge_draw_unchanged():
    """Common random numbers: adding manual tasks does not change a truck's discharge (tipping) time draw."""
    base = site()
    del base["unloading_labour"], base["operator_pools"]
    tasks = [task("position", 1, [1, 2, 4]), task("discharge", 0, "tip")]
    with_tasks = site(workers=1, tasks=tasks)
    for raw in (base, with_tasks):
        for e in raw["equipment"]:
            if e["type"] == "hopper":
                e["tip"] = [3, 5, 9]
    a = load_site_config(base)
    b = load_site_config(with_tasks)
    sa, sb = StochasticServiceTimes(a, 7), StochasticServiceTimes(b, 7)
    assert sa.duration_ms("T1", "tip", "HA") == sb.duration_ms("T1", "tip", "HA")
    d = sb.duration_ms("T1", "tip:position", "HA")
    assert hm("00:01") <= d <= hm("00:04") and d == StochasticServiceTimes(b, 7).duration_ms("T1", "tip:position", "HA")


@pytest.mark.parametrize("change, words", [
    (lambda raw: raw["unloading_labour"].update(pool="nobody"), "unknown operator pool"),
    (lambda raw: raw["operator_pools"][0].update(skills=["sample"]), "skill tip"),
    (lambda raw: raw.update(labour=[{"step": "tip", "pool": "unloaders"}]), "not both"),
    (lambda raw: raw["unloading_labour"]["tasks"].pop(1), 'time "tip"'),
    (lambda raw: raw["unloading_labour"]["tasks"].insert(0, task("sweep", 1, [1, 1, 1], present=False)), "come first"),
    (lambda raw: raw["unloading_labour"]["tasks"][2].update(operators=3), "never has that many"),
    (lambda raw: raw["unloading_labour"]["tasks"][0].update(time=[3, 2, 1]), "in that order"),
    (lambda raw: raw.update(staffing_scenarios={"x": {"labour": {"tip:nope": 1}}}), "no labour requirement"),
])
def test_invalid_unloading_labour_is_refused(change, words):
    raw = site(workers=2)
    change(raw)
    with pytest.raises(ModelError) as err:
        run(raw, [("T1", "07:00")])
    assert words in str(err.value)


def test_audit_detects_a_task_without_its_workers():
    raw = site(workers=1)
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": "07:00", "commodity": "YM", "tonnes": 30} for t in ("T1", "T2")]})
    r = TruckFlowModel(s, script, TIMES, policy="feasible_first").run()
    r.labour_use = [u for u in r.labour_use if u["owner"] != "T2/tip#2"]
    assert any("T2/tip task scrape ran without its workers" in p for p in audit_flow(s, script, r).problems)
    r2 = TruckFlowModel(s, script, TIMES, policy="feasible_first").run()
    r2.labour_use.append(dict(r2.labour_use[0], owner="ghost"))
    assert any("exceeds" in p for p in audit_flow(s, script, r2).problems)


# ---- staffing levels against targets (experiments.staffing_search) ----
def search_site(close="18:00", **kw):
    raw = site(**kw)
    h, mnt = close.split(":")
    raw["hours"] = {"open": 7, "close": int(h) + int(mnt) / 60, "overtime": 1}
    return load_site_config(raw)


def scripted(trucks):
    return lambda s, seed: load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": 30} for t, at in trucks]})


def test_minimum_workforce_meets_turnaround_and_overtime_targets():
    """Two trucks at 07:00 with fixed times (as in test_one_worker_cannot_do_two_tasks). 1 worker: T1 departs 07:10,
    T2 07:13 -> mean turnaround 11.5 min; 2 or 3 workers: both 07:10 -> 10 min. Closing 07:12: overtime 1 min with
    1 worker, 0 with 2. Targets: turnaround <= 10.5 min, overtime <= 0.5 min -> minimum 2 workers."""
    from silo_engine.experiments.staffing_search import StaffingTargets, minimum_workforce
    r = minimum_workforce(search_site(close="07:12"), "unloaders", [3, 1, 2],
                          StaffingTargets(max_mean_turnaround_min=10.5, max_overtime_min=0.5),
                          replications=2, arrivals=scripted([("T1", "07:00"), ("T2", "07:00")]))
    by = {lv.workers: lv for lv in r.levels}
    assert [lv.workers for lv in r.levels] == [1, 2, 3]
    assert by[1].summary["mean_turnaround_min"]["mean"] == 11.5 and by[2].summary["mean_turnaround_min"]["mean"] == 10
    assert (by[1].summary["overtime_min"]["mean"], by[2].summary["overtime_min"]["mean"]) == (1, 0)
    assert by[1].meets == {"mean_turnaround_min": False, "overtime_min": False} and by[2].all_met and by[3].all_met
    assert (r.minimum, r.non_monotonic) == (2, False)
    assert r.metadata["status"].startswith("calculation on unverified inputs")


def test_failed_runs_count_against_a_level():
    """Bins of 30 t: T1's lot fills BA; T3's lot (HA) can never leave the pit, so every run stalls. The level fails
    its targets and the stalls are reported, not left out."""
    from silo_engine.experiments.staffing_search import StaffingTargets, minimum_workforce
    s = search_site(workers=1)
    raw = s.model_dump(by_alias=True)
    for e in raw["equipment"]:
        if e["type"] == "bin":
            e["capT"] = 30
    s = load_site_config(raw)
    r = minimum_workforce(s, "unloaders", [1], StaffingTargets(min_completion_rate=0.0), replications=2,
                          arrivals=scripted([("T1", "07:00"), ("T2", "07:00"), ("T3", "07:30")]))
    assert r.levels[0].statuses == ["stalled", "stalled"] and r.levels[0].meets == {"completion_rate": False}
    assert r.minimum is None
