"""User-defined truck steps (docs/PLATFORM_GAP_ANALYSIS.md step 6, gap G2). Hand-traced. Test inputs only.

A site can add a step without code: `custom_steps: [{id, label, equipment}]` names a step served at equipment of the
generic type `station` (lanes `cap`, time per truck `time`). The step can be placed in any truck sequence and path,
held by release rules, given worker phases, and start background tasks, like a built-in station step.

Site: incoming bridge WB_IN with 2 lanes (2 min), a document station DOCS (3 min), one hopper (tip 5 min), outgoing
bridge (2 min). Sequence weigh_in -> documents -> tip -> weigh_out; no truck path (unlimited waiting before steps).
"""
import copy

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config
from silo_engine.config.report import prerun_report
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel
from test_background_tasks import BASE

TIMES = FixedServiceTimes({"weigh_in": 2, "documents": 3, "tip": 5, "weigh_out": 2, "task:cleared": 10})
STEP = [{"id": "documents", "label": "Document check", "equipment": ["DOCS"]}]


def raw(cap=1, **extra):
    r = copy.deepcopy(BASE)
    r["equipment"] = [e for e in r["equipment"] if e["id"] != "OFFICE"]
    r["equipment"].append({"id": "DOCS", "type": "station", "name": "Document check", "cap": cap, "time": [3, 3, 3]})
    r["custom_steps"] = copy.deepcopy(STEP)
    r["sequences"] = {"unload": ["weigh_in", "documents", "tip", "weigh_out"]}
    r.update(copy.deepcopy(extra))
    return r


def run(r, trucks=(("T1", "07:00"), ("T2", "07:00"))):
    s = load_site_config(r)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": 30} for t, at in trucks]})
    m = TruckFlowModel(s, script, TIMES, policy="feasible_first").run()
    audit = audit_flow(s, script, m)
    assert m.violations == [] and m.material_balance_kg == 0 and m.stall is None
    assert audit.ok, audit.problems
    return m


def times(r, step):
    return {x.truck_id: next((s.unit, s.started, s.finished) for s in x.steps if s.step == step) for x in r.records}


def test_a_user_defined_step_is_served_at_its_station():
    """T1, T2 weigh in 07:00-07:02 on the two lanes. One document station: T1 07:02-07:05, T2 07:05-07:08.
    Tipping: T1 07:05-07:10, T2 07:10-07:15 (hopper busy until 07:10)."""
    r = run(raw())
    assert times(r, "documents") == {"T1": ("DOCS#0", hm("07:02"), hm("07:05")), "T2": ("DOCS#0", hm("07:05"), hm("07:08"))}
    assert times(r, "tip") == {"T1": ("H1", hm("07:05"), hm("07:10")), "T2": ("H1", hm("07:10"), hm("07:15"))}


def test_a_user_defined_step_can_need_workers_and_hold_trucks():
    """Two document lanes but one clerk for the whole check (phases): T1 07:02-07:05, T2 07:05-07:08. With a
    release rule on documents waiting for a 10-minute background task 'cleared' started by weigh-in, T1 stays at
    the document station until 07:12."""
    pool = [{"id": "clerks", "skills": ["documents"], "schedule": [{"from": "07:00", "to": "18:00", "count": 1}]}]
    phases = [{"step": "documents", "pool": "clerks", "phases": [{"id": "check", "workers": 1, "time": "service"}]}]
    r = run(raw(cap=2, operator_pools=pool, task_phases=phases))
    assert {t: (s, e) for t, (_, s, e) in times(r, "documents").items()} == {"T1": (hm("07:02"), hm("07:05")), "T2": (hm("07:05"), hm("07:08"))}
    task = [{"id": "cleared", "started_by": "weigh_in", "time": [10, 10, 10], "produces": "cleared"}]
    rule = [{"activity": "unload", "step": "documents", "when": ["service_done", "cleared"]}]
    held = run(raw(background_tasks=task, release_rules=rule), trucks=(("T1", "07:00"),))
    docs = next(s for s in held.records[0].steps if s.step == "documents")
    assert (docs.finished, docs.left) == (hm("07:05"), hm("07:12"))


def test_built_in_sites_are_unaffected():
    """A site without custom steps validates and runs exactly as before (the full suite and the evidence
    reproduction check this broadly); a station not used by any step is reported."""
    r = raw()
    r["sequences"] = {"unload": ["weigh_in", "tip", "weigh_out"]}
    assert "stations.unused" in [f.code for f in prerun_report(load_site_config(r)).findings]
    run(r)


def test_an_undeclared_step_is_refused_when_the_configuration_is_read():
    from silo_engine.config import ConfigSchemaError
    r = raw()
    r["sequences"] = {"unload": ["weigh_in", "inspect", "tip", "weigh_out"]}
    with pytest.raises(ConfigSchemaError, match="unknown step inspect"):
        load_site_config(r)


@pytest.mark.parametrize("change, words", [
    (lambda r: r.update(custom_steps=STEP + [{"id": "weigh_in", "label": "x", "equipment": ["DOCS"]}]), "built-in step"),
    (lambda r: r.update(custom_steps=[{"id": "documents", "label": "x", "equipment": ["WB_IN"]}]), "type station"),
    (lambda r: r.update(custom_steps=[{"id": "documents", "label": "x", "equipment": ["GHOST"]}]), "unknown equipment GHOST"),
    (lambda r: r.update(custom_steps=STEP + STEP), "more than once"),
])
def test_invalid_custom_steps_are_refused(change, words):
    r = raw()
    change(r)
    with pytest.raises(ModelError) as err:
        run(r)
    assert words in str(err.value)
