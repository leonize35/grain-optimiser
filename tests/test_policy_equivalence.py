"""Prototype versus Python engine: the same admission decisions for identical equipment states, queues and policies.

tests/golden/policy_equivalence.json holds scenarios (prototype-format configurations) and the trace of the
UNMODIFIED prototype engine for each (captured by `python tools/policy_equivalence.py` in headless Edge). Here the
Python engine runs the same configuration with the prototype's trucks (opening backlog, same ids, commodities and
tonnes) and the prototype's `policies` translated by `queue_policy.from_prototype` (the only translation), and every
admission decision is compared: weighbridge starts, tipping starts (truck and hopper), grain transfers (start time,
commodity, tonnes, route), loading starts (truck, route) and departures.

All durations are fixed ([a, a, a]); hoppers are large, so the prototype's stepwise hopper level and the Python
engine's continuous drain (A3) cannot affect admission.
"""
import hashlib
import json
import re
from pathlib import Path

import pytest

from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.queue_policy import UnsupportedPrototypePolicy, from_prototype
from silo_engine.sim.service_times import StochasticServiceTimes
from silo_engine.sim.time import MS_PER_MINUTE
from silo_engine.sim.truck_flow import TruckFlowModel

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = json.loads((ROOT / "tests" / "golden" / "policy_equivalence.json").read_text(encoding="utf-8"))
SUPPORTED = [s for s in GOLDEN["scenarios"] if s["supported"]]
UNSUPPORTED = [s for s in GOLDEN["scenarios"] if not s["supported"]]
ACTIVITY = {"Unloading": "unload", "Loading": "load"}


def _names(config):
    eq = {e["name"]: e["id"] for e in config["equipment"]}
    com = {c["name"]: c["id"] for c in config["commodities"]}
    return eq, com


def prototype_decisions(scenario):
    eq, com = _names(scenario["config"])
    trucks, out = [], []
    for t, msg in scenario["prototype"]["trace"]:
        t = round(t, 6)
        if m := re.fullmatch(r"(\S+) arrives \((\w+), (.+) ([\d.]+) t\)", msg):
            trucks.append((m[1], ACTIVITY[m[2]], com[m[3]], float(m[4]), t))
        elif m := re.fullmatch(r"(\S+) starts tipping [\d.]+ t into (.+)", msg):
            out.append((t, "tip", m[1], eq[m[2]]))
        elif m := re.fullmatch(r"(\S+) starts (weigh-in|weigh-out) at (.+)", msg):
            out.append((t, m[2].replace("-", "_"), m[1], eq[m[3]]))
        elif m := re.fullmatch(r"Transfer ([\d.]+) t (.+?): (.+?)(?: \(changeover .*\))?", msg):
            out.append((t, "intake", com[m[2]], f"{float(m[1]):.2f}", tuple(eq[x] for x in m[3].split(" > "))))
        elif m := re.fullmatch(r"(\S+) starts loading from (.+?) via (.+)", msg):
            out.append((t, "load", m[1], tuple([eq[m[2]]] + [eq[x] for x in m[3].split(" > ")])))
        elif m := re.fullmatch(r"(\S+) departs", msg):
            out.append((t, "depart", m[1]))
    return trucks, sorted(out)


def python_run(scenario, trucks):
    site = load_site_config(scenario["config"])
    script = load_arrival_script({"trucks": [
        {"id": tid, "activity": act, "arrive": f"{int(t // 60):02d}:{int(t % 60):02d}", "commodity": c, "tonnes": kg}
        for tid, act, c, kg, t in trucks]})
    policy = from_prototype(site.policies.model_dump())
    model = TruckFlowModel(site, script, StochasticServiceTimes(site, scenario["seed"]), policy=policy)
    return site, model.run()


def python_decisions(scenario, trucks):
    site, r = python_run(scenario, trucks)
    minutes = lambda ms: round(ms / MS_PER_MINUTE, 6)  # noqa: E731
    commodity = {t[0]: t[2] for t in trucks}
    level = {e.id: e.level_commodity for e in site.equipment if e.type == "hopper"}
    out = []
    for rec in r.records:
        for s in rec.steps:
            if s.started is None:
                continue
            if s.step == "tip":
                out.append((minutes(s.started), "tip", rec.truck_id, s.unit))
            elif s.step in ("weigh_in", "weigh_out"):
                out.append((minutes(s.started), s.step, rec.truck_id, s.unit.split("#")[0]))
        if rec.departed is not None:
            out.append((minutes(rec.departed), "depart", rec.truck_id))
    for x in r.transfers:
        c = commodity[x.truck_id] if x.truck_id else level[x.pit]
        out.append((minutes(x.started), "intake", c, f"{x.kg / 1000:.2f}", tuple(x.path)))
    for x in r.loads:
        out.append((minutes(x.started), "load", x.truck_id, tuple(x.path)))
    return r, sorted(out)


def test_golden_was_captured_from_the_unmodified_prototype():
    engine = ROOT / "reference" / "prototype_js" / "silo_engine_v0.2.0.js"
    assert GOLDEN["engine_sha256"] == hashlib.sha256(engine.read_bytes()).hexdigest()
    assert all("error" not in s["prototype"] and s["prototype"]["violations"] == [] for s in GOLDEN["scenarios"])


# Known difference (reported, not approved for change): when two pits' head lots have exactly the same age, the
# prototype transfers from the pit listed first in the configuration; this engine from the pit whose transfer
# request was queued first. Shared-conveyor scenarios: under tip=fifo the head lots of H1 and H2 both date from
# 440 min (tie decided at 480); under tip=feasible both from 422 min (decided at 435, delaying yellow trucks).
EQUAL_AGE_TIE = {"two_shared_opening_grain/tip=fifo": 480, "two_shared_opening_grain/tip=feasible": 435}
CASES = [pytest.param(s, marks=pytest.mark.xfail(strict=True, reason="equal-age intake tie-break differs"))
         if s["name"] in EQUAL_AGE_TIE else s for s in SUPPORTED]


@pytest.mark.parametrize("scenario", CASES, ids=[s["name"] for s in SUPPORTED])
def test_same_admission_decisions_as_the_prototype(scenario):
    trucks, expected = prototype_decisions(scenario)
    r, actual = python_decisions(scenario, trucks)
    assert r.violations == [] and r.material_balance_kg == 0 and r.stall is None
    assert actual == expected


def test_the_two_prototype_tip_policies_really_differ_in_these_scenarios():
    """Guards against a vacuous comparison: in at least one layout strict FIFO and feasible-first decide differently."""
    by_name = {s["name"]: prototype_decisions(s)[1] for s in SUPPORTED}
    layouts = {s["layout"] for s in SUPPORTED}
    assert sum(by_name[f"{x}/tip=fifo"] != by_name[f"{x}/tip=feasible"] for x in layouts) >= 3


@pytest.mark.parametrize("scenario", UNSUPPORTED, ids=[s["name"] for s in UNSUPPORTED])
def test_prototype_rules_without_an_equivalent_are_refused_not_approximated(scenario):
    site = load_site_config(scenario["config"])
    with pytest.raises(UnsupportedPrototypePolicy):
        from_prototype(site.policies.model_dump())


def test_translation_table():
    assert from_prototype({"tip": "fifo", "weigh": "fifo", "transfer": "fifo"}) == {
        "tip": "strict_fifo", "weigh": "feasible_first", "intake": "feasible_first", "load": "feasible_first",
        "sample": "feasible_first", "grade": "feasible_first", "move": "feasible_first"}
    assert from_prototype({"tip": "feasible"})["tip"] == "feasible_first"
    assert from_prototype(None)["tip"] == "strict_fifo"  # the prototype's default tip rule is strict FIFO


@pytest.mark.parametrize("name", sorted(EQUAL_AGE_TIE))
def test_the_only_difference_is_the_equal_age_intake_tie(name, monkeypatch):
    """Diagnostic: decisions match the prototype up to the first equal-age tie, and match completely when the
    prototype's tie-break (pit configuration order among intake requests of the same grain age) is substituted.
    The substitution is local to this test; the engine's rule is unchanged."""
    from silo_engine.sim import dispatcher as dispatcher_module
    scenario = next(s for s in SUPPORTED if s["name"] == name)
    trucks, expected = prototype_decisions(scenario)
    _, actual = python_decisions(scenario, trucks)
    t = EQUAL_AGE_TIE[name]
    assert [d for d in actual if d[0] < t] == [d for d in expected if d[0] < t]
    assert [d for d in actual if d[0] >= t] != [d for d in expected if d[0] >= t]
    pit_order = [e["id"] for e in scenario["config"]["equipment"] if e["type"] == "hopper"]
    original = dispatcher_module._Pending.position

    def prototype_tie_break(self):
        key, seq = original(self)
        return (key, pit_order.index(self.id.split("/")[0])) if self.group == "intake" else (key, seq)

    monkeypatch.setattr(dispatcher_module._Pending, "position", prototype_tie_break)
    _, substituted = python_decisions(scenario, trucks)
    assert substituted == expected


def _note(result):
    return [a for a in result.assumptions if "prototype policies" in a]


def test_prototype_policies_are_noted_when_they_differ_from_what_ran():
    """Behaviour unchanged: the prototype field is not applied; the run says so when it differs."""
    base = next(s for s in SUPPORTED if s["name"] == "one_hopper/tip=fifo")
    trucks, _ = prototype_decisions(base)
    cfg = json.loads(json.dumps(base["config"]))
    site = load_site_config(cfg)
    script = load_arrival_script({"trucks": [
        {"id": tid, "activity": act, "arrive": "07:00", "commodity": c, "tonnes": kg} for tid, act, c, kg, _ in trucks]})
    r = TruckFlowModel(site, script, StochasticServiceTimes(site, 1)).run()  # no argument, no queue_policies
    assert r.queue_policies["tip"] == "feasible_first" and r.policy_source == "default"
    assert len(_note(r)) == 1 and "tip='fifo'" in _note(r)[0] and "not applied" in _note(r)[0]
    same = load_site_config({**cfg, "policies": {"tip": "feasible", "weigh": "fifo", "transfer": "fifo"}})
    assert _note(TruckFlowModel(same, script, StochasticServiceTimes(same, 1)).run()) == []
    batch = load_site_config({**cfg, "policies": {"tip": "batch", "weigh": "fifo", "transfer": "fifo"}})
    assert "no equivalent" in _note(TruckFlowModel(batch, script, StochasticServiceTimes(batch, 1)).run())[0]
    unset = load_site_config({k: v for k, v in cfg.items() if k != "policies"})
    assert _note(TruckFlowModel(unset, script, StochasticServiceTimes(unset, 1)).run()) == []


def test_golden_sites_get_no_note_because_their_prototype_policies_match():
    raw = next(c for c in json.loads((ROOT / "tests" / "golden" / "validation_cases.json").read_text(encoding="utf-8"))["cases"]
               if c["name"] == "site_a_valid")["config"]
    site = load_site_config(json.loads(json.dumps(raw)))
    assert from_prototype(site.policies.model_dump()) == {g: "feasible_first" for g in from_prototype(None)}
