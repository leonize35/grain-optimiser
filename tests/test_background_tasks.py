"""Background tasks (docs/PLATFORM_GAP_ANALYSIS.md step 4, primitive P1). Hand-traced. Test inputs only.

A background task is work done off the truck, started when a truck finishes a chosen step (e.g. documents prepared
at the office after weighing in). It may occupy a lane of a station (one task at a time per lane) and/or workers
of a pool, takes its own time, and when done produces a named condition for that truck. Release rules (P3) can
wait for that condition, so a truck may be held on its place until the task is done. A task never occupies a
truck place.

Built-in grading (sample -> grade) is unchanged; a background task configured like grading gives identical times.
"""
import copy

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes, StochasticServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel
from test_grading_blocking import RAW as GRADING, bridge_occupancy

# Site without sampling: two incoming-bridge lanes (2 min), one hopper (tip 5 min), outgoing bridge (2 min).
BASE = copy.deepcopy(GRADING)
BASE["equipment"] = [e for e in BASE["equipment"] if e["id"] not in ("S1", "G1")]
next(e for e in BASE["equipment"] if e["id"] == "WB_IN")["cap"] = 2
BASE["equipment"].append({"id": "OFFICE", "type": "grader", "name": "Document office", "cap": 1, "time": [6, 6, 6]})
BASE["sequences"] = {"unload": ["weigh_in", "tip", "weigh_out"]}
DOCS = {"id": "documents", "started_by": "weigh_in", "time": [6, 6, 6], "produces": "documents"}
HOLD = [{"activity": "unload", "step": "weigh_in", "when": ["service_done", "documents"]}]
TIMES = FixedServiceTimes({"sample": 4, "grade": 10, "weigh_in": 2, "tip": 5, "weigh_out": 2, "task:documents": 6,
                           "task:check": 10})


def run(raw, trucks, times=TIMES):
    s = load_site_config(copy.deepcopy(raw))
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": 30} for t, at in trucks]})
    r = TruckFlowModel(s, script, times, policy="feasible_first").run()
    audit = audit_flow(s, script, r)
    assert r.violations == [] and r.material_balance_kg == 0 and r.stall is None
    assert audit.ok, audit.problems
    return r


def with_(**extra):
    raw = copy.deepcopy(BASE)
    raw.update(copy.deepcopy(extra))
    return raw


def log(r):
    return [(x["truck"], x["task"], x["unit"], x["start"], x["end"]) for x in r.background_log]


def test_a_task_at_a_station_lane_queues_and_holds_trucks():
    """T1, T2 at 07:00 weigh in on the two lanes 07:00-07:02. Documents at the one-lane office: T1 07:02-07:08,
    T2 waits for the office and is done 07:08-07:14. Each truck stays on its bridge lane until its documents are
    done: T1 leaves 07:08 and tips 07:08-07:13; T2 leaves 07:14 and tips 07:14-07:19."""
    r = run(with_(background_tasks=[{**DOCS, "equipment": ["OFFICE"]}], release_rules=HOLD), [("T1", "07:00"), ("T2", "07:00")])
    assert log(r) == [("T1", "documents", "OFFICE#0", hm("07:02"), hm("07:08")), ("T2", "documents", "OFFICE#0", hm("07:08"), hm("07:14"))]
    assert sorted(bridge_occupancy(r)) == [("T1", hm("07:00"), hm("07:08")), ("T2", hm("07:00"), hm("07:14"))]


def test_a_task_done_by_workers_of_a_pool():
    """The same with one clerk instead of the office: identical times."""
    raw = with_(background_tasks=[{**DOCS, "pool": "clerks"}], release_rules=HOLD,
                operator_pools=[{"id": "clerks", "skills": ["documents"], "schedule": [{"from": "07:00", "to": "18:00", "count": 1}]}])
    r = run(raw, [("T1", "07:00"), ("T2", "07:00")])
    assert [(t, s, e) for t, _, _, s, e in log(r)] == [("T1", hm("07:02"), hm("07:08")), ("T2", hm("07:08"), hm("07:14"))]
    assert [(u["owner"], u["start"], u["end"]) for u in r.labour_use] == [("T1/task:documents", hm("07:02"), hm("07:08")),
                                                                         ("T2/task:documents", hm("07:08"), hm("07:14"))]


def test_a_task_without_resources_is_a_delay_and_without_a_rule_holds_nothing():
    r = run(with_(background_tasks=[DOCS]), [("T1", "07:00"), ("T2", "07:00")])
    assert [(t, s, e) for t, _, u, s, e in log(r)] == [("T1", hm("07:02"), hm("07:08")), ("T2", hm("07:02"), hm("07:08"))]
    assert sorted(bridge_occupancy(r)) == [("T1", hm("07:00"), hm("07:02")), ("T2", hm("07:00"), hm("07:02"))]


def test_a_release_can_wait_for_grading_and_a_task_together():
    """Grading site (sampler 4 min, grading 10 min). Documents (6 min, no resources) start after weigh-in. T1:
    weighed 07:04-07:06; documents 07:06-07:12; graded 07:14: it leaves the bridge at 07:14. With 1-minute grading
    (result 07:05) it leaves when the documents are done, 07:12."""
    raw = copy.deepcopy(GRADING)
    raw["background_tasks"] = [DOCS]
    raw["release_rules"] = [{"activity": "unload", "step": "weigh_in", "when": ["service_done", "graded", "documents"]}]
    assert bridge_occupancy(run(raw, [("T1", "07:00")]))[0] == ("T1", hm("07:04"), hm("07:14"))
    fast = FixedServiceTimes({"sample": 4, "grade": 1, "weigh_in": 2, "tip": 5, "weigh_out": 2, "task:documents": 6})
    assert bridge_occupancy(run(raw, [("T1", "07:00")], fast))[0] == ("T1", hm("07:04"), hm("07:12"))


def test_a_task_configured_like_grading_gives_the_same_times():
    """Equivalence with built-in grading (tests/test_grading_blocking.py, first test): a task "check" started by
    sampling at its own one-lane station, 10 min, with weigh-in released when checked."""
    from test_grading_blocking import RAW as G, run as run_grading
    builtin = run_grading([("T1", "07:00"), ("T2", "07:01"), ("T3", "07:02")],
                          release_rules=[{"activity": "unload", "step": "weigh_in", "when": ["service_done", "graded"]}])
    raw = copy.deepcopy(G)
    raw["sequences"] = {"unload": ["sample", "weigh_in", "tip", "weigh_out"]}  # no built-in grading
    raw["equipment"].append({"id": "CHECK", "type": "grader", "name": "Check station", "cap": 1, "time": [10, 10, 10]})
    raw["background_tasks"] = [{"id": "check", "started_by": "sample", "equipment": ["CHECK"], "time": [10, 10, 10], "produces": "checked"}]
    raw["release_rules"] = [{"activity": "unload", "step": "weigh_in", "when": ["service_done", "checked"]}]
    task = run(raw, [("T1", "07:00"), ("T2", "07:01"), ("T3", "07:02")],
               FixedServiceTimes({"sample": 4, "weigh_in": 2, "tip": 5, "weigh_out": 2, "task:check": 10}))
    assert bridge_occupancy(task) == bridge_occupancy(builtin)
    assert [next(s.started for s in x.steps if s.step == "tip") for x in task.records] == \
        [next(s.started for s in x.steps if s.step == "tip") for x in builtin.records]


def test_task_times_are_drawn_without_changing_other_draws():
    raw = with_(background_tasks=[{**DOCS, "time": [3, 6, 12]}])
    base = copy.deepcopy(BASE)
    a, b = StochasticServiceTimes(load_site_config(base), 9), StochasticServiceTimes(load_site_config(raw), 9)
    assert a.duration_ms("T1", "weigh_in", "WB_IN") == b.duration_ms("T1", "weigh_in", "WB_IN")
    d = b.duration_ms("T1", "task:documents", "")
    assert hm("00:03") <= d <= hm("00:12") and d == StochasticServiceTimes(load_site_config(raw), 9).duration_ms("T1", "task:documents", "")


@pytest.mark.parametrize("tasks, rules, extra, words", [
    ([{**DOCS, "equipment": ["GHOST"]}], [], {}, "unknown equipment GHOST"),
    ([{**DOCS, "pool": "nobody"}], [], {}, "unknown operator pool nobody"),
    ([{**DOCS, "produces": "graded"}], [], {}, "reserved"),
    ([DOCS, {**DOCS, "id": "again"}], [], {}, "more than one background task produces documents"),
    ([{**DOCS, "started_by": "sample"}], [], {}, "no truck process has sample"),
    ([{**DOCS, "started_by": "tip"}], HOLD, {}, "would wait for ever"),
    ([], HOLD, {}, "unknown condition documents"),
    ([{**DOCS, "pool": "clerks", "workers": 2}], [], {"operator_pools": [{"id": "clerks", "skills": ["documents"],
      "schedule": [{"from": "07:00", "to": "18:00", "count": 1}]}]}, "never has that many"),
    ([{**DOCS, "pool": "clerks"}], [], {"operator_pools": [{"id": "clerks", "skills": ["weigh_in"],
      "schedule": [{"from": "07:00", "to": "18:00", "count": 1}]}]}, "skill documents"),
])
def test_invalid_background_tasks_are_refused(tasks, rules, extra, words):
    with pytest.raises(ModelError) as err:
        run(with_(background_tasks=tasks, release_rules=rules, **extra), [("T1", "07:00")])
    assert words in str(err.value)


def test_audit_detects_a_task_started_before_its_step_finished():
    raw = with_(background_tasks=[DOCS])
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [{"id": "T1", "activity": "unload", "arrive": "07:00", "commodity": "YM", "tonnes": 30}]})
    r = TruckFlowModel(s, script, TIMES, policy="feasible_first").run()
    r.background_log[0]["start"] = hm("07:01")
    assert any("started before" in p for p in audit_flow(s, script, r).problems)
