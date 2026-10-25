"""A sampler restricted to activities (checklist A8, G-C2) and loading trucks sampled after loading (A9, G-C3).
Hand-traced. Inputs are test values, not Ventersdorp data.

Site (tests/test_loading.py layout plus samplers and directional bridges): receiving sampler S_REC (unload only)
and a loading sampling point S_LOAD (load only); incoming bridge WB_IN and outgoing WB_OUT (2 min each); hopper H1
(tip 1 min); bin B1 with 100 t; load-out B1 -> R1 -> E1 -> L1 (setup 5 min + 30 t at 200 t/h = 14 min).
Receiving: sample (4 min) -> weigh_in -> tip -> weigh_out. Loading: weigh_in -> load -> sample (3 min) -> weigh_out.
Trucks at 07:00 in this order: U1, U2 (receiving, 30 t), L1 (loading, 30 t).
"""
import copy

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel
from test_loading import BASE, trucks

TIMES = FixedServiceTimes({"sample": 4, "tip": 1, "weigh_in": 2, "weigh_out": 2, "load": 5}, {("L1", "sample"): 3})


def site(restricted=True):
    raw = copy.deepcopy(BASE)
    eq = [e for e in raw["equipment"] if e["id"] != "WB1"]
    eq += [{"id": "S_REC", "type": "sampler", "name": "Receiving sampler", "cap": 1, "time": [4, 4, 4]},
           {"id": "S_LOAD", "type": "sampler", "name": "Loading sampling point", "cap": 1, "time": [3, 3, 3]},
           {"id": "WB_IN", "type": "weighbridge", "name": "Incoming", "cap": 1, "moves": "in", "time": [2, 2, 2]},
           {"id": "WB_OUT", "type": "weighbridge", "name": "Outgoing", "cap": 1, "moves": "out", "time": [2, 2, 2]}]
    if restricted:
        eq[-4]["activities"], eq[-3]["activities"] = ["unload"], ["load"]
    raw["equipment"] = eq
    raw["sequences"] = {"unload": ["sample", "weigh_in", "tip", "weigh_out"],
                        "load": ["weigh_in", "load", "sample", "weigh_out"]}
    return raw


SCRIPT = [("U1", "unload", "07:00", 30, {}), ("U2", "unload", "07:00", 30, {}), ("L1", "load", "07:00", 30, {})]


def run(raw):
    s, script = load_site_config(raw), trucks(*SCRIPT)
    r = TruckFlowModel(s, script, TIMES, policy="feasible_first").run()
    audit = audit_flow(s, script, r)
    assert r.violations == [] and r.material_balance_kg == 0 and r.stall is None
    assert audit.ok, audit.problems
    return r


def steps(r, tid):
    rec = next(x for x in r.records if x.truck_id == tid)
    return [(s.step, s.unit, s.started, s.finished) for s in rec.steps]


def test_receiving_trucks_never_use_the_loading_sampling_point():
    """U1 is sampled at S_REC 07:00-07:04. U2 waits for S_REC (07:04-07:08) although S_LOAD is free: S_LOAD serves
    loading trucks only. L1 is sampled at S_LOAD after loading."""
    r = run(site())
    assert steps(r, "U1")[0] == ("sample", "S_REC#0", hm("07:00"), hm("07:04"))
    assert steps(r, "U2")[0] == ("sample", "S_REC#0", hm("07:04"), hm("07:08"))
    assert [s for s in steps(r, "L1") if s[0] == "sample"] == [("sample", "S_LOAD#0", hm("07:16"), hm("07:19"))]


def test_without_restriction_any_sampler_serves_any_truck():
    """Default (no activities): U2 takes the free S_LOAD at 07:00."""
    assert steps(run(site(restricted=False)), "U2")[0][:3] == ("sample", "S_LOAD#0", hm("07:00"))


def test_loading_truck_is_sampled_after_loading():
    """L1: WB_IN 07:00-07:02; load 07:02-07:16 (setup 5 + 9 min flow); sample at S_LOAD 07:16-07:19; WB_OUT
    07:19-07:21. The loading sample is not graded and gates nothing."""
    r = run(site())
    assert steps(r, "L1") == [("weigh_in", "WB_IN#0", hm("07:00"), hm("07:02")),
                              ("load", "L1", hm("07:02"), hm("07:16")),
                              ("sample", "S_LOAD#0", hm("07:16"), hm("07:19")),
                              ("weigh_out", "WB_OUT#0", hm("07:19"), hm("07:21"))]
    assert "S-L1" not in r.samples
    assert next(x for x in r.records if x.truck_id == "L1").departed == hm("07:21")


def test_an_activity_with_sampling_needs_a_sampler_that_serves_it():
    raw = site()
    raw["equipment"] = [e for e in raw["equipment"] if e["id"] != "S_LOAD"]
    with pytest.raises(ModelError, match="No sampler serves loading trucks"):
        run(raw)
