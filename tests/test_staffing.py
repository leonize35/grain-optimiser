"""Operator pools, labour requirements and staffing scenarios (docs/OPERATOR_STAFFING_DESIGN.md). Hand-traced.

The pools, counts and windows here are TEST INPUTS, not facts about any silo (all marked unverified).

Site: one sampler (1 probe, 4 min), one weighbridge with 2 bays (2 min); unloading = sample, weigh_in; no truck path,
so trucks wait in unlimited areas between steps. Trucks T1 and T2 arrive 07:00, T3 07:01; all need sampling.
Without labour: T1 sample 07:00-07:04, weigh 07:04-07:06; T2 sample 07:04-07:08, weigh 07:08-07:10;
T3 sample 07:08-07:12, weigh 07:12-07:14.
"""
import copy

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.ledger import LaneClaim, LabourClaim, ReservationLedger
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel
from test_starvation_diagnostics import ONE_HOPPER

TIMES = FixedServiceTimes({"sample": 4, "weigh_in": 2})
TRUCKS = [("T1", "07:00"), ("T2", "07:00"), ("T3", "07:01")]


def site(**extra):
    raw = copy.deepcopy(ONE_HOPPER)
    raw["sequences"] = {"unload": ["sample", "weigh_in"]}
    raw["equipment"] = raw["equipment"] + [
        {"id": "S1", "type": "sampler", "name": "Sampler", "cap": 1, "time": [4, 4, 4]},
        {"id": "WB1", "type": "weighbridge", "name": "Weighbridge", "cap": 2, "time": [2, 2, 2]}]
    raw.update(extra)
    return raw


def pool(pid, skills, windows, verified=False):
    return {"id": pid, "name": pid, "skills": skills, "verified": verified,
            "schedule": [{"from": a, "to": b, "count": n} for a, b, n in windows]}


def run(raw, staffing=None, trucks=TRUCKS, sequence=None):
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": 30} for t, at in trucks]})
    r = TruckFlowModel(s, script, TIMES, policy="feasible_first", staffing=staffing).run()
    audit = audit_flow(s, script, r)
    assert r.violations == [] and r.material_balance_kg == 0 and r.stall is None
    assert audit.ok, audit.problems
    return r


def times(r, step):
    return {x.truck_id: next((s.started, s.finished) for s in x.steps if s.step == step) for x in r.records}


def decisions(r):
    return ([(e.time, e.label) for e in r.trace if "staff" not in e.label], r.records)


def test_no_labour_configured_changes_nothing():
    r = run(site())
    assert times(r, "sample") == {"T1": (hm("07:00"), hm("07:04")), "T2": (hm("07:04"), hm("07:08")), "T3": (hm("07:08"), hm("07:12"))}
    assert (r.staffing, r.labour_use, r.waiting_attribution) == ({}, [], {})


def test_one_shared_operator_serialises_sampling_and_weighing():
    """One operator does both tasks (a truck keeps its place until it moves; waiting requests are tried in queue
    order).
    07:04 T1 finishes sampling; T1's weigh-in request appears only after T1 has moved off the probe, so T2's sampling
          (queued 07:00) takes the operator: T2 samples 07:04-07:08.
    07:08 T2 finishes sampling but is still on the probe at that instant; T1's weigh-in (waiting since 07:04) takes
          the operator: T1 weighs 07:08-07:10. T3's sampling (queued 07:01) then waits for the operator.
    07:10 T3 samples 07:10-07:14. 07:14 T2 weighs 07:14-07:16 (waiting since 07:08). 07:16 T3 weighs 07:16-07:18.
    A second weighbridge bay is free throughout: labour, not equipment, is the constraint.
    Waiting (truck-minutes): sampler busy 11 (T2 07:00-07:04, T3 07:01-07:08); operator busy 14 (T1 4, T2 6, T3 2+2).
    Operator busy 3 x 4 + 3 x 2 = 18 min of 660 available (07:00-18:00)."""
    raw = site(operator_pools=[pool("crew", ["sample", "weigh_in"], [("07:00", "18:00", 1)])],
               labour=[{"step": "sample", "pool": "crew"}, {"step": "weigh_in", "pool": "crew"}])
    r = run(raw)
    assert times(r, "sample") == {"T1": (hm("07:00"), hm("07:04")), "T2": (hm("07:04"), hm("07:08")), "T3": (hm("07:10"), hm("07:14"))}
    assert times(r, "weigh_in") == {"T1": (hm("07:08"), hm("07:10")), "T2": (hm("07:14"), hm("07:16")), "T3": (hm("07:16"), hm("07:18"))}
    w = r.waiting_attribution
    assert (w["LABOUR_UNAVAILABLE:crew"], w["EQUIPMENT_BUSY:S1"]) == (14.0, 11.0)  # truck-minutes
    u = r.staffing["pools"]["crew"]
    assert (u["busy_operator_minutes"], u["available_operator_minutes"], u["verified"]) == (18.0, 660.0, False)
    assert any("unverified" in a and "crew" in a for a in r.assumptions)


def test_a_second_operator_at_a_single_probe_gives_no_gain_without_a_crew_time_rule():
    base = run(site())
    raw = site(operator_pools=[pool("samplers", ["sample"], [("07:00", "18:00", 2)])],
               labour=[{"step": "sample", "pool": "samplers"}])
    assert decisions(run(raw)) == decisions(base)


def test_crew_time_applies_only_where_configured():
    """Scenario: two operators per sampling with a crew-time factor 0.5 -> 2 min sampling.
    T1 07:00-07:02, T2 07:02-07:04, T3 07:04-07:06; weighing 2 min each right after."""
    raw = site(operator_pools=[pool("samplers", ["sample"], [("07:00", "18:00", 2)])],
               labour=[{"step": "sample", "pool": "samplers"}],
               staffing_scenarios={"two_at_probe": {"labour": {"sample": 2}}},
               crew_time={"sample": {"2": 0.5}})
    r = run(raw, staffing="two_at_probe")
    assert times(r, "sample") == {"T1": (hm("07:00"), hm("07:02")), "T2": (hm("07:02"), hm("07:04")), "T3": (hm("07:04"), hm("07:06"))}
    assert r.staffing["scenario"] == "two_at_probe"
    assert decisions(run(raw)) == decisions(run(site()))  # baseline (1 operator per sampling): unchanged times


def test_a_shift_end_does_not_interrupt_a_running_task():
    """One sampling operator 07:00-07:06, then none until a second shift from 07:20. T2 starts at 07:04 and
    finishes at 07:08 (no pre-emption at 07:06); T3 waits for the next shift and samples 07:20-07:24."""
    raw = site(operator_pools=[pool("samplers", ["sample"], [("07:00", "07:06", 1), ("07:20", "18:00", 1)])],
               labour=[{"step": "sample", "pool": "samplers"}])
    r = run(raw)
    assert times(r, "sample") == {"T1": (hm("07:00"), hm("07:04")), "T2": (hm("07:04"), hm("07:08")), "T3": (hm("07:20"), hm("07:24"))}


def test_a_scenario_changes_staffing_without_changing_equipment():
    """Baseline: one sampling operator from 07:10 only; scenario adds one from 07:00. Equipment unchanged."""
    raw = site(operator_pools=[pool("samplers", ["sample"], [("07:10", "18:00", 1)])],
               labour=[{"step": "sample", "pool": "samplers"}],
               staffing_scenarios={"early_seasonal": {"pools": {"samplers": [{"from": "07:00", "to": "18:00", "count": 1}]}}})
    base = run(raw)
    assert times(base, "sample")["T1"] == (hm("07:10"), hm("07:14"))
    assert decisions(run(raw, staffing="early_seasonal")) == decisions(run(site()))


def test_start_only_releases_the_operator_when_the_task_starts():
    """Weigh-in only, 2 bays, 1 clerk. Whole task: the second truck starts at 07:02. Start only: both at 07:00."""
    trucks = [("T1", "07:00"), ("T2", "07:00")]
    for held, second in (("whole_task", hm("07:02")), ("start_only", hm("07:00"))):
        raw = site(sequences={"unload": ["weigh_in"]},
                   operator_pools=[pool("clerks", ["weigh_in"], [("07:00", "18:00", 1)])],
                   labour=[{"step": "weigh_in", "pool": "clerks", "held": held}])
        assert times(run(raw, trucks=trucks), "weigh_in")["T2"][0] == second


def test_labour_and_equipment_are_reserved_together_or_not_at_all():
    ledger = ReservationLedger({"WB1#0"}, {}, {}, {}, pools={"clerks": 1})
    assert ledger.try_reserve("a", [LaneClaim("WB1#0")], 0) == []
    reasons = ledger.try_reserve("b", [LaneClaim("WB1#0"), LabourClaim("clerks", 1)], 0)
    assert [r.code for r in reasons] == ["EQUIPMENT_BUSY"] and ledger.pool_in_use("clerks") == 0
    ledger.release("a", 0, "completed")
    assert ledger.try_reserve("b", [LaneClaim("WB1#0"), LabourClaim("clerks", 1)], 0) == []
    assert ledger.pool_in_use("clerks") == 1
    assert [r.code for r in ledger.check([LabourClaim("clerks", 1)], 0)] == ["LABOUR_UNAVAILABLE"]


@pytest.mark.parametrize("change, words", [
    (lambda raw: raw.update(labour=[{"step": "sample", "pool": "nobody"}]), "unknown operator pool"),
    (lambda raw: raw.update(labour=[{"step": "weigh_in", "pool": "samplers"}]), "skill"),
    (lambda raw: raw.update(labour=[{"step": "sample", "pool": "samplers", "operators": 3}]), "never"),
    (lambda raw: raw.update(staffing_scenarios={"x": {"pools": {"ghost": []}}}), "unknown operator pool"),
    (lambda raw: raw.update(crew_time={"sample": {"2": 0}}), "positive"),
])
def test_invalid_staffing_is_refused(change, words):
    raw = site(operator_pools=[pool("samplers", ["sample"], [("07:00", "18:00", 2)])], labour=[{"step": "sample", "pool": "samplers"}])
    change(raw)
    with pytest.raises(ModelError) as err:
        run(raw)
    assert words in str(err.value)


def test_unknown_scenario_is_refused():
    raw = site(operator_pools=[pool("samplers", ["sample"], [("07:00", "18:00", 1)])], labour=[{"step": "sample", "pool": "samplers"}])
    with pytest.raises(ModelError):
        run(raw, staffing="nope")


@pytest.mark.parametrize("corrupt, words", [
    (lambda r: r.labour_use.append(dict(r.labour_use[0], owner="ghost", start=r.labour_use[0]["start"] + 1)), "exceeds"),
    (lambda r: r.labour_use.pop(0), "without its operators"),
])
def test_audit_detects_labour_violations(corrupt, words):
    raw = site(operator_pools=[pool("crew", ["sample", "weigh_in"], [("07:00", "18:00", 1)])],
               labour=[{"step": "sample", "pool": "crew"}, {"step": "weigh_in", "pool": "crew"}])
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": 30} for t, at in TRUCKS]})
    r = TruckFlowModel(s, script, TIMES, policy="feasible_first").run()
    bad = copy.deepcopy(r)
    corrupt(bad)
    problems = audit_flow(s, script, bad).problems
    assert any(words in p for p in problems), problems
