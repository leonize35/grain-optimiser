"""Per-silo hours (gap G-D5; semantics confirmed by the user 2026-11-07). Hand-traced. Test inputs only.

- A system's admission cut-off: a truck admitted at the gate before the cut-off may still be sent to that system
  later (it is on site and is processed to completion); a truck admitted after it can only go to other systems.
  The shared gate admits until the site's own cut-off.
- A system's overtime: its hoppers may start tipping until closing + that overtime. The shared stations keep the
  site's overtime, which the system's may not exceed.
- Clearance is reported per system ("unassigned": trucks that never reached a hopper).

Site: Silo A (hopper HA -> CA -> EA -> bins BA YM, BA2 WM) and Silo B (HB -> CB -> EB -> BB YM). HA accepts YM and
WM, HB only YM. Pits 120 t (no space waits), tipping 5 min, weigh-in 5 min where used.
"""
import copy

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel
from test_unloading_labour import site as two_silo

TIMES = FixedServiceTimes({"tip": 5, "weigh_in": 5})


def site(a_hours=None, b_hours=None, hours=None, weigh=False):
    r = two_silo(workers=1)
    del r["unloading_labour"], r["operator_pools"]
    r["commodities"] = [{"id": "YM", "name": "Yellow maize"}, {"id": "WM", "name": "White maize"}]
    for e in r["equipment"]:
        if e["type"] == "hopper":
            e.update(capT=120, tip=[5, 5, 5])
        if e["id"] == "HA":
            e["commodities"] = ["YM", "WM"]
    r["equipment"].append({"id": "BA2", "type": "bin", "name": "BA2", "capT": 1000, "commodities": ["WM"]})
    r["edges"].append(["EA", "BA2"])
    r["systems"] = [{"id": "A", "name": "Silo A", "equipment": ["HA", "CA", "EA", "BA", "BA2"]},
                    {"id": "B", "name": "Silo B", "equipment": ["HB", "CB", "EB", "BB"]}]
    if a_hours is not None:
        r["systems"][0]["hours"] = a_hours
    if b_hours is not None:
        r["systems"][1]["hours"] = b_hours
    if hours:
        r["hours"] = hours
    if weigh:
        r["equipment"].append({"id": "WB1", "type": "weighbridge", "name": "WB1", "cap": 1, "time": [5, 5, 5]})
        r["sequences"] = {"unload": ["weigh_in", "tip"]}
    return r


def run(raw, trucks):
    s = load_site_config(copy.deepcopy(raw))
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": c, "tonnes": 30} for t, at, c in trucks]})
    r = TruckFlowModel(s, script, TIMES, policy="feasible_first").run()
    audit = audit_flow(s, script, r)
    assert r.violations == [] and r.material_balance_kg == 0 and r.stall is None
    assert audit.ok, audit.problems
    return r


def tip(r, t):
    rec = next(x for x in r.records if x.truck_id == t)
    return next(((s.unit, s.started) for s in rec.steps if s.step == "tip"), (None, None))


def test_after_a_silos_cut_off_new_trucks_go_to_the_other_silo():
    """Silo A cut-off 07:12 (7.2 h). T1 (07:00) tips at HA 07:00-07:05. T2 is admitted at 07:12, not before A's
    cut-off: it goes to HB at 07:12, although HA is free and holds its grain. Without the cut-off T2 tips at HA."""
    trucks = [("T1", "07:00", "YM"), ("T2", "07:12", "YM")]
    r = run(site(a_hours={"admission_cutoff": 7.2}), trucks)
    assert (tip(r, "T1"), tip(r, "T2")) == (("HA", hm("07:00")), ("HB", hm("07:12")))
    assert tip(run(site(), trucks), "T2") == ("HA", hm("07:12"))


def test_a_truck_admitted_before_the_cut_off_may_still_go_there():
    """Weigh-in 5 min first. Silo A cut-off 07:12 (7.2). T1 WM 07:00: weighs 07:00-07:05, tips HA 07:05-07:10.
    T2 WM arrives 07:08 (before the cut-off): weighs 07:08-07:13 and tips at HA 07:13, after the cut-off.
    T3 WM arrives 07:13 (after): weighs 07:13-07:18, but only HA takes white maize and Silo A no longer takes new
    trucks: T3 waits (silo closed) and is unfinished at the end of the day, without a stall."""
    r = run(site(a_hours={"admission_cutoff": 7.2}, weigh=True),
            [("T1", "07:00", "WM"), ("T2", "07:08", "WM"), ("T3", "07:13", "WM")])
    assert (tip(r, "T1"), tip(r, "T2"), tip(r, "T3")) == (("HA", hm("07:05")), ("HA", hm("07:13")), (None, None))
    assert r.outcomes["trucks"]["T3"]["status"] == "unfinished_on_site"


def test_each_silo_has_its_own_overtime_and_clearance():
    """Site: close 07:15, overtime 1 h. Silo A overtime 0 (stops at 07:15), Silo B uses 1 h (to 08:15).
    WM (only HA): T1 07:00-07:05, T2 07:05-07:10, T3 07:10-07:15; T4 would start at 07:15, A's stop: unfinished.
    YM at HB: T5 07:04-07:09, T6 07:09-07:14, T7 07:14-07:19, T8 07:19-07:24 (after closing, within B's overtime).
    Clearance: A cleared at 07:15 (no overtime); B cleared at 07:24 (9 min overtime); T4 unassigned, not cleared."""
    r = run(site(a_hours={"overtime": 0}, b_hours={"overtime": 1}, hours={"open": 7, "close": 7.25, "overtime": 1}),
            [("T1", "07:00", "WM"), ("T2", "07:01", "WM"), ("T3", "07:02", "WM"), ("T4", "07:03", "WM"),
             ("T5", "07:04", "YM"), ("T6", "07:05", "YM"), ("T7", "07:06", "YM"), ("T8", "07:07", "YM")])
    assert [tip(r, t)[1] for t in ("T1", "T2", "T3", "T4")] == [hm("07:00"), hm("07:05"), hm("07:10"), None]
    assert [tip(r, t) for t in ("T7", "T8")] == [("HB", hm("07:14")), ("HB", hm("07:19"))]
    c = r.outcomes["clearance_by_system"]
    assert (c["A"][0]["cleared"], c["A"][0]["final_clearance"], c["A"][0]["overtime_used_min"]) == (True, hm("07:15"), 0)
    assert (c["B"][0]["cleared"], c["B"][0]["final_clearance"], c["B"][0]["overtime_used_min"]) == (True, hm("07:24"), 9)
    assert (c["unassigned"][0]["cleared"], c["unassigned"][0]["remaining"]) == (False, ["T4"])
    assert c["A"][0]["hard_stop"] == hm("07:15") and c["B"][0]["hard_stop"] == hm("08:15")


def test_without_silo_hours_nothing_changes():
    trucks = [("T1", "07:00", "YM"), ("T2", "07:12", "YM")]
    a, b = run(site(), trucks), run(site(a_hours={}), trucks)
    assert [(e.time, e.label) for e in a.trace] == [(e.time, e.label) for e in b.trace]
    assert "clearance_by_system" not in a.outcomes


@pytest.mark.parametrize("a_hours, words", [
    ({"admission_cutoff": 19}, "gate cut-off"),
    ({"admission_cutoff": 6}, "gate cut-off"),
    ({"overtime": 2}, "shared"),
])
def test_invalid_silo_hours_are_refused(a_hours, words):
    with pytest.raises(ModelError) as err:
        run(site(a_hours=a_hours, hours={"open": 7, "close": 18, "overtime": 1}), [("T1", "07:00", "YM")])
    assert words in str(err.value)
