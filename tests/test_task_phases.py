"""Worker phases for any step (docs/PLATFORM_GAP_ANALYSIS.md step 5, primitive P4). Hand-traced. Test inputs only.

`task_phases` splits a step into phases, each with its own number of workers from one pool; the phase with time
"service" takes the station's own time. Workers are released between phases; a truck keeps its station and waits
for the workers of its next phase. For stations (sampling, weighing) every phase has the truck present. For
unloading (`tip`), `task_phases` is another way of writing `unloading_labour` and gives identical results.

Site (tests/test_staffing.py layout): sampler with 2 lanes (4 min), weighbridge with 2 lanes (2 min);
sequence sample -> weigh_in; trucks T1 and T2 at 07:00, both sampled 07:00-07:04 and at the bridge at 07:04.
"""
import copy

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel
from test_staffing import site as staffing_site
from test_unloading_labour import TIMES as UL_TIMES, site as unloading_site, tasks_of, tip_times

MS = 60_000
TIMES = FixedServiceTimes({"sample": 4, "weigh_in": 2, "weigh_in:check_in": 0.5})
CLERKS = [{"id": "clerks", "skills": ["weigh_in"], "schedule": [{"from": "07:00", "to": "18:00", "count": 1}]}]
PHASED = [{"step": "weigh_in", "pool": "clerks", "phases": [
    {"id": "check_in", "workers": 1, "time": [0.5, 0.5, 0.5]}, {"id": "weigh", "workers": 0, "time": "service"}]}]


def site(**extra):
    raw = staffing_site()
    next(e for e in raw["equipment"] if e["id"] == "S1")["cap"] = 2
    raw["operator_pools"] = copy.deepcopy(CLERKS)
    raw.update(copy.deepcopy(extra))
    return raw


def run(raw, trucks=(("T1", "07:00"), ("T2", "07:00")), times=TIMES):
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": 30} for t, at in trucks]})
    r = TruckFlowModel(s, script, times, policy="feasible_first").run()
    audit = audit_flow(s, script, r)
    assert r.violations == [] and r.material_balance_kg == 0 and r.stall is None
    assert audit.ok, audit.problems
    return r


def weigh(r):
    return {x.truck_id: next((s.started, s.finished) for s in x.steps if s.step == "weigh_in") for x in r.records}


def test_a_clerk_needed_only_to_check_in():
    """One clerk, needed only for a 30 s check-in. T1: check-in 07:04:00-07:04:30, weighing 07:04:30-07:06:30.
    The workers of a step's first phase are taken together with the station place (as for unloading tasks), so T2
    takes the second lane when the clerk is free: check-in 07:04:30-07:05:00, weighing 07:05-07:07."""
    r = run(site(task_phases=PHASED))
    assert weigh(r) == {"T1": (hm("07:04"), hm("07:06") + MS // 2), "T2": (hm("07:04") + MS // 2, hm("07:07"))}
    assert [(u["owner"], u["step"], u["start"], u["end"]) for u in r.labour_use] == [
        ("T1/weigh_in#0", "weigh_in:check_in", hm("07:04"), hm("07:04") + MS // 2),
        ("T2/weigh_in#0", "weigh_in:check_in", hm("07:04") + MS // 2, hm("07:05"))]


def test_phases_differ_from_whole_task_and_start_only_labour():
    """Same clerk held for the whole weighing: T2 weighs 07:06-07:08. Held only to start: both 07:04-07:06."""
    whole = run(site(labour=[{"step": "weigh_in", "pool": "clerks", "held": "whole_task"}]))
    start = run(site(labour=[{"step": "weigh_in", "pool": "clerks", "held": "start_only"}]))
    assert weigh(whole)["T2"] == (hm("07:06"), hm("07:08")) and weigh(start)["T2"] == (hm("07:04"), hm("07:06"))


def test_without_task_phases_nothing_changes():
    assert weigh(run(site()))["T2"] == (hm("07:04"), hm("07:06"))


@pytest.mark.parametrize("allocation", ["oldest_task_first", "started_trucks_first"])
def test_tip_phases_are_another_form_of_unloading_labour(allocation):
    """The unloading-labour scenarios of tests/test_unloading_labour.py written as task_phases for `tip` give
    identical worker use and unloading times."""
    trucks = [("T1", "07:00"), ("T2", "07:00"), ("T3", "07:00")]
    old = unloading_site(workers=1, allocation=allocation)
    new = copy.deepcopy(old)
    ul = new.pop("unloading_labour")
    new["task_phases"] = [{"step": "tip", "pool": ul["pool"], "allocation": allocation, "phases": [
        {"id": t["id"], "workers": t["operators"], "time": t["time"] if t["time"] != "tip" else "service",
         "truck_present": t["truck_present"]} for t in ul["tasks"]]}]
    a, b = run(old, trucks, UL_TIMES), run(new, trucks, UL_TIMES)
    assert tip_times(a) == tip_times(b) and tasks_of(a) == tasks_of(b)


@pytest.mark.parametrize("phases, words", [
    ([{"step": "load", "pool": "clerks", "phases": [{"id": "x", "workers": 1, "time": "service"}]}], "not supported for load"),
    ([{"step": "weigh_in", "pool": "clerks", "phases": [{"id": "x", "workers": 1, "time": [1, 1, 1]}]}], 'time "service"'),
    ([{"step": "weigh_in", "pool": "clerks", "phases": [{"id": "x", "workers": 1, "time": "service", "truck_present": False}]}], "truck present"),
    ([{"step": "weigh_in", "pool": "nobody", "phases": [{"id": "x", "workers": 1, "time": "service"}]}], "unknown operator pool nobody"),
    ([{"step": "sample", "pool": "clerks", "phases": [{"id": "x", "workers": 1, "time": "service"}]}], "skill sample"),
    ([{"step": "weigh_in", "pool": "clerks", "phases": [{"id": "x", "workers": 2, "time": "service"}]}], "never has that many"),
    (PHASED + PHASED, "more than once"),
])
def test_invalid_task_phases_are_refused(phases, words):
    with pytest.raises(ModelError) as err:
        run(site(task_phases=phases))
    assert words in str(err.value)


def test_phases_and_a_labour_requirement_for_the_same_step_are_refused():
    with pytest.raises(ModelError, match="not both"):
        run(site(task_phases=PHASED, labour=[{"step": "weigh_in", "pool": "clerks"}]))
