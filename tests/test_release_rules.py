"""Conditions and release rules (docs/PLATFORM_GAP_ANALYSIS.md step 3, primitives P2 and P3). Hand-traced.

A release rule says when a truck may leave the place where a step was done: when the service is done *and* every
listed condition holds for that truck (and, as always, it has its next place). The first condition is `graded`:
the truck's sample has been graded. Service time is unaffected.

The confirmed receiving rule "weighed even if grading is pending, then stays on the incoming weighbridge until the
result" was expressed so far only by an explicit truck path with no area between weigh_in and grade
(tests/test_grading_blocking.py, the old form). The new form states it directly and needs no truck path:
    release_rules: [{"activity": "unload", "step": "weigh_in", "when": ["service_done", "graded"]}]
Site and times as in tests/test_grading_blocking.py (sampler 4 min, grading 10 min, bridges 2 min, tip 5 min).
"""
import copy

import pytest

from silo_engine.config import load_site_config
from silo_engine.config.report import prerun_report
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError
from test_grading_blocking import RAW, bridge_occupancy, paths, run, step

TRUCKS = [("T1", "07:00"), ("T2", "07:01"), ("T3", "07:02")]
RULE = [{"activity": "unload", "step": "weigh_in", "when": ["service_done", "graded"]}]


def times(r):
    return {rec.truck_id: [(s.step, s.unit, s.started, s.finished) for s in rec.steps] for rec in r.records}


def test_release_rule_holds_the_bridge_without_a_truck_path():
    """Same hand trace as test_truck_waiting_for_grading_holds_the_incoming_weighbridge: T1 on WB_IN 07:04-07:14
    (weighed 07:04-07:06, result 07:14), T2 07:14-07:24, T3 07:24-07:34."""
    r = run(TRUCKS, release_rules=RULE)
    assert bridge_occupancy(r) == [("T1", hm("07:04"), hm("07:14")), ("T2", hm("07:14"), hm("07:24")),
                                   ("T3", hm("07:24"), hm("07:34"))]
    assert (step(r, "T1", "weigh_in").started, step(r, "T1", "weigh_in").finished) == (hm("07:04"), hm("07:06"))
    assert step(r, "T1", "tip").started == hm("07:14")


def test_new_form_equals_the_old_form():
    """Every step of every truck starts and ends at the same times, on the same units, as with the explicit path."""
    old = run(TRUCKS, **paths())
    new = run(TRUCKS, release_rules=RULE)
    assert times(new) == times(old)
    assert bridge_occupancy(new) == bridge_occupancy(old)
    both = run(TRUCKS, release_rules=RULE, **paths())  # rule and explicit path together: no double effect
    assert times(both) == times(old)


def test_without_a_rule_behaviour_is_unchanged():
    assert bridge_occupancy(run(TRUCKS))[0] == ("T1", hm("07:04"), hm("07:06"))


def test_a_truck_that_is_not_sampled_is_not_held():
    """`graded` applies only to trucks that are sampled: T1 (requires_sampling false) leaves WB_IN after weighing."""
    raw = copy.deepcopy(RAW)
    raw["release_rules"] = RULE
    from silo_engine.inputs.scripted import load_arrival_script
    from silo_engine.sim.service_times import FixedServiceTimes
    from silo_engine.sim.truck_flow import TruckFlowModel
    script = load_arrival_script({"trucks": [{"id": "T1", "activity": "unload", "arrive": "07:00", "commodity": "YM",
                                              "tonnes": 30, "requires_sampling": False}]})
    times_ = FixedServiceTimes({"sample": 4, "grade": 10, "weigh_in": 2, "tip": 5, "weigh_out": 2, "pass": 0})
    r = TruckFlowModel(load_site_config(raw), script, times_, policy="feasible_first").run()
    wi = step(r, "T1", "weigh_in")
    assert wi.left == wi.finished


def test_fast_result_adds_no_hold():
    r = run(TRUCKS, grade_min=1, release_rules=RULE)
    assert bridge_occupancy(r)[0] == ("T1", hm("07:04"), hm("07:06"))


@pytest.mark.parametrize("rules, words", [
    ([{"activity": "unload", "step": "weigh_in", "when": ["inspected"]}], "unknown condition inspected"),
    ([{"activity": "load", "step": "weigh_in", "when": ["graded"]}], "not in the loading sequence"),
    ([RULE[0], RULE[0]], "more than one release rule"),
])
def test_invalid_release_rules_are_refused(rules, words):
    with pytest.raises(ModelError) as err:
        run(TRUCKS, release_rules=rules)
    assert words in str(err.value)


def test_a_rule_on_a_later_step_is_allowed():
    """Holding the outgoing bridge until graded is a valid (if unusual) rule: the result is long there by then."""
    r = run(TRUCKS, release_rules=[{"activity": "unload", "step": "weigh_out", "when": ["graded"]}])
    assert r.stall is None


def test_graded_needs_grading_in_the_sequence():
    raw = copy.deepcopy(RAW)
    raw["sequences"]["unload"] = ["sample", "weigh_in", "tip", "weigh_out"]
    with pytest.raises(ModelError, match="no grading"):
        run(TRUCKS, sequences=raw["sequences"], release_rules=RULE)


def test_a_condition_produced_only_after_the_held_step_is_refused():
    """Holding the sampler is fine (grading starts when sampling ends), but a rule on a step before sampling would
    wait for a result that can only come later: refused."""
    seq = {"unload": ["weigh_in", "sample", "grade", "tip", "weigh_out"]}
    with pytest.raises(ModelError, match="before sampling"):
        run(TRUCKS, sequences=seq, release_rules=RULE)


def test_report_no_longer_warns_about_a_hold_stated_by_a_rule():
    raw = copy.deepcopy(RAW)
    assert "process.hold_without_path" in [f.code for f in prerun_report(load_site_config(raw)).findings]
    raw["release_rules"] = RULE
    assert "process.hold_without_path" not in [f.code for f in prerun_report(load_site_config(raw)).findings]
