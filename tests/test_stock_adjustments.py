"""Stock adjustments and reconciliation (docs/STOCK_ADJUSTMENTS.md): independent physical (P), book (R) and observed
(O) records; process losses; observations; authorised book corrections; reconciliation with an explicit
unexplained part. Every case is also checked by the engine's mass balance and the independent flow audit.

Site (tests/test_loading.py): B1 opens with 100 t of yellow maize. L1 (30 t) loads 07:00-07:14 (5 min setup + 9 min).
U1 tips 30 t 07:00-07:01; its lot waits for the shared elevator and flows into B1 07:14-07:23.
"""
import copy
import dataclasses

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import ConfigSchemaError, load_site_config
from silo_engine.experiments.runner import kpis_of
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel
from test_loading import BASE as LOADING_SITE

L1 = ("L1", "load", "07:00", 30)
U1 = ("U1", "unload", "07:00", 30)
WHO = {"reason": "survey accepted by stock controller", "authority": "site manager"}


def loss(t, tonnes, cause="moisture", posted=True, at="07:30"):
    return {"kind": "process_loss", "time": at, "bin": "B1", "tonnes": tonnes, "cause": cause, "posted": posted}


def survey(observed, sid="S1", at="07:30"):
    return {"kind": "stock_measurement", "id": sid, "time": at, "bin": "B1", "observed_tonnes": observed}


def admin(tonnes, at="06:00", **who):
    return {"kind": "book_correction", "time": at, "bin": "B1", "basis": "administrative", "tonnes": tonnes,
            **(who or WHO)}


def accept(sid="S1", at="08:00"):
    return {"kind": "book_correction", "time": at, "bin": "B1", "basis": "measurement", "observation": sid, **WHO}


def run(events=(), trucks=(L1, U1), tolerance=None, **site_changes):
    raw = copy.deepcopy(LOADING_SITE)
    raw["sequences"] = {"unload": ["tip"], "load": ["load"]}
    raw["stock_events"] = list(events)
    raw.update(site_changes)
    site = load_site_config(raw)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": act, "arrive": at, "commodity": "YM", "tonnes": kg} for t, act, at, kg in trucks]})
    model = TruckFlowModel(site, script, FixedServiceTimes({"tip": 1, "load": 5}), policy="feasible_first",
                           reconciliation_tolerance=tolerance)
    r = model.run()
    audit = audit_flow(site, script, r)
    assert r.material_balance_kg == 0 and r.violations == []
    assert audit.ok, audit.problems
    assert all(x.unexplained_kg == 0 for x in r.reconciliation.values())
    return r, site, script


def rec(r, key="B1"):
    x = r.reconciliation[key]
    return (x.physical_kg, x.book_kg, x.difference_kg)


def test_v1_without_stock_events_book_equals_physical_and_nothing_is_flagged():
    r, *_ = run()
    assert rec(r) == (100_000, 100_000, 0) and rec(r, "site") == (100_000, 100_000, 0)
    assert (r.losses, r.observations, r.stock_log) == ([], [], [])
    assert r.book == {"B1": 100_000}


def test_v2_posted_moisture_loss_is_a_labelled_generic_mass_loss():
    r, *_ = run([loss(None, 2)])
    assert rec(r) == (98_000, 98_000, 0)
    assert [(x.bin, x.kg, x.cause, x.posted, x.time) for x in r.losses] == [("B1", 2_000, "moisture", True, hm("07:30"))]
    assert r.bins["B1"][1].commodity == "YM"  # identity and grade unchanged
    assert any("generic" in a and "moisture" in a.lower() for a in r.assumptions)
    assert kpis_of(r)["losses.moisture_t"] == 2


def test_v3_unposted_loss_shows_as_an_explained_discrepancy():
    r, *_ = run([loss(None, 2, posted=False)])
    x = r.reconciliation["B1"]
    assert rec(r) == (98_000, 100_000, 2_000)
    assert (x.unposted_loss_kg, x.opening_difference_kg, x.administrative_kg, x.survey_based_kg) == (2_000, 0, 0, 0)


def test_v4_loss_larger_than_uncommitted_stock_is_refused_in_full():
    r, *_ = run([loss(None, 80, at="07:05")])
    assert [(e.kind, e.applied, e.delta_physical_kg, e.delta_book_kg) for e in r.stock_log] == [("process_loss", False, 0, 0)]
    assert "uncommitted" in r.stock_log[0].refused_because
    assert r.losses == [] and rec(r) == (100_000, 100_000, 0) and r.loads[0].finished == hm("07:14")


def test_v5_administrative_book_stock_cannot_be_loaded():
    r, *_ = run([admin(5)], trucks=[("L2", "load", "07:00", 103)])
    x = r.reconciliation["B1"]
    assert rec(r) == (100_000, 105_000, 5_000) and x.administrative_kg == 5_000
    assert r.dispatched_kg == 0 and r.stall is not None
    assert [w.code for w in r.stall.waiting["L2/load"]] == ["STOCK_SHORT"]


def test_v6_book_correction_that_would_make_the_book_negative_is_refused():
    r, *_ = run([admin(-120)])
    assert (r.stock_log[0].applied, r.stock_log[0].delta_book_kg) == (False, 0)
    assert rec(r) == (100_000, 100_000, 0)


@pytest.mark.parametrize("tolerance, flagged", [(None, False), ({"tolerance_t": 1}, True), ({"tolerance_t": 5}, False)])
def test_v7_a_survey_is_an_observation_only(tolerance, flagged):
    r, *_ = run([survey(97)], reconciliation=tolerance) if tolerance else run([survey(97)])
    o = r.observations[0]
    assert (o.id, o.time, o.observed_kg, o.physical_kg, o.book_kg) == ("S1", hm("07:30"), 97_000, 100_000, 100_000)
    assert (o.minus_book_kg, o.minus_physical_kg, o.flagged) == (-3_000, -3_000, flagged)
    assert rec(r) == (100_000, 100_000, 0)  # neither P nor R changed


def test_v7b_an_authorised_correction_posts_the_accepted_survey_to_the_book():
    r, *_ = run([survey(97), accept()])
    x = r.reconciliation["B1"]
    assert rec(r) == (100_000, 97_000, -3_000) and x.survey_based_kg == -3_000
    assert r.stock_log[1].delta_book_kg == -3_000 and r.stock_log[1].delta_physical_kg == 0


def test_v8_opening_book_difference_is_carried_through_intake_and_loading():
    r, *_ = run(opening_book=[{"bin": "B1", "tonnes": 105}])
    x = r.reconciliation["B1"]
    assert rec(r) == (100_000, 105_000, 5_000) and x.opening_difference_kg == 5_000


def test_v9_a_loss_that_empties_a_bin_clears_its_identity():
    r, *_ = run([loss(None, 100, cause="handling", at="06:30")], trucks=[])
    assert r.bins["B1"] == (0, None) and rec(r) == (0, 0, 0)


def test_v10_mixed_day_all_equations_hold():
    events = [admin(2, at="06:30"), loss(None, 1, cause="cleaning", posted=False, at="07:05"),
              survey(95, at="07:30"), loss(None, 3, cause="handling", at="07:40"), accept(at="08:00")]
    r, *_ = run(events)
    x = r.reconciliation["B1"]
    # P: 100 - 1 (07:05) - 30 load + 30 intake = 99 at the 07:30 survey, - 3 = 96. R: 100 + 2 - 30 + 30 = 102 at the
    # survey, - 3 posted = 99, then survey-based
    # correction at 08:00: O 95 - R 99 = -4 -> 95.
    assert rec(r) == (96_000, 95_000, -1_000)
    assert (x.administrative_kg, x.unposted_loss_kg, x.survey_based_kg, x.unexplained_kg) == (2_000, 1_000, -4_000, 0)
    assert r.observations[0].book_kg == 102_000 and r.observations[0].physical_kg == 99_000


# ---- the audit detects corrupted records ----

@pytest.mark.parametrize("corrupt, words", [
    (lambda r: r.bins.__setitem__("B1", (r.bins["B1"][0] + 5_000, r.bins["B1"][1])), "bin B1"),
    (lambda r: r.losses.clear(), "bin B1"),
    (lambda r: r.reconciliation.__setitem__("B1", dataclasses.replace(r.reconciliation["B1"], administrative_kg=0)), "unexplained"),
    (lambda r: r.observations.__setitem__(0, dataclasses.replace(r.observations[0], physical_kg=1)), "observation"),
    (lambda r: r.book.__setitem__("B1", r.book["B1"] + 1), "book"),
])
def test_v11_audit_detects_corrupted_stock_records(corrupt, words):
    r, site, script = run([admin(2, at="06:30"), loss(None, 1, posted=False, at="07:05"), survey(95)])
    bad = copy.deepcopy(r)
    corrupt(bad)
    problems = audit_flow(site, script, bad).problems
    assert any(words in p for p in problems), problems


# ---- configuration and authority ----

@pytest.mark.parametrize("event, words", [
    ({**admin(5), "reason": ""}, "reason"),
    ({k: v for k, v in admin(5).items() if k != "authority"}, "authority"),
    ({**loss(None, 2), "bin": "ZZ"}, "unknown bin"),
    ({**loss(None, -2)}, "positive"),
    ({**accept(), "observation": "nope"}, "unknown observation"),
    ({**loss(None, 2), "cause": "magic"}, "cause"),
])
def test_v12_invalid_stock_events_are_refused(event, words):
    with pytest.raises((ModelError, ConfigSchemaError)) as err:
        run([event], trucks=[])
    assert words in str(err.value)


def test_v12_authority_must_be_listed_when_the_site_restricts_it():
    with pytest.raises(ModelError) as err:
        run([admin(5)], trucks=[], authorised_by=["stock controller"])
    assert "not authorised" in str(err.value)
    r, *_ = run([admin(5, reason="count error", authority="stock controller")], trucks=[],
                authorised_by=["stock controller"])
    assert r.book["B1"] == 105_000


def test_v12_a_correction_before_its_observation_is_refused_at_run_time():
    r, *_ = run([survey(97, at="09:00"), accept(at="08:00")])
    assert [(e.kind, e.applied) for e in r.stock_log] == [("book_correction", False), ("stock_measurement", True)]
    assert "not yet" in r.stock_log[0].refused_because


def test_v13_run_tolerance_overrides_the_site():
    r, *_ = run([survey(97)], reconciliation={"tolerance_t": 5}, tolerance={"tolerance_t": 1})
    assert r.observations[0].flagged is True
    r, *_ = run([survey(97)], tolerance={"tolerance_fraction": 0.05})  # 5 % of a 100 t book = 5 t
    assert r.observations[0].flagged is False
