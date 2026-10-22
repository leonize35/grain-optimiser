"""Commodity-pair changeovers (R3) and route clear time (R1 clear_minutes). Build step 3.

Route timing: reserved -> changeover (longest segment, A5) -> grain flows -> clear time -> released.
Routes run at 200 t/h (elevator), so a 30 t lot flows for 9 min. Trucks tip in 1 min.
Scenario used throughout: hopper H1 accepts yellow (YM) and white maize (WM); route H1 -> C1 -> E1 -> B1 (YM) or
B2 (WM). T1 arrives 07:00, tips 07:00-07:01; its lot flows 07:01-07:10 (first use of the route: no changeover).
T2 (other commodity) arrives 07:00, must wait for an empty pit (07:10), tips 07:10-07:11; its lot is reserved
at 07:11 and flows after the changeover.
"""
from decimal import Decimal

import pytest

from silo_engine.config import load_site_config
from silo_engine.config.rules_validation import validate_rules
from silo_engine.domain.changeover import AmbiguousRule, ChangeoverMatrix
from silo_engine.domain.storage import GradedCommodity
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel

YM, WM, SB = GradedCommodity("YM", "*"), GradedCommodity("WM", "*"), GradedCommodity("SB", "*")


def site(changeovers=None, c1_extra=None, e1_extra=None, commodities=("YM", "WM"), with_h2=False):
    eq = [{"id": "H1", "type": "hopper", "name": "Hopper 1", "capT": 60, "rate": 400, "tip": [1, 1, 1],
           "commodities": list(commodities)},
          {"id": "C1", "type": "conveyor", "name": "Pit conveyor", "rate": 300, **(c1_extra or {})},
          {"id": "E1", "type": "elevator", "name": "Elevator 1", "rate": 200, **(e1_extra or {})},
          {"id": "B1", "type": "bin", "name": "Bin 1", "capT": 1000, "commodities": ["YM"]},
          {"id": "B2", "type": "bin", "name": "Bin 2", "capT": 1000, "commodities": ["WM"]},
          {"id": "B3", "type": "bin", "name": "Bin 3", "capT": 1000, "commodities": ["SB"]}]
    edges = [["H1", "C1"], ["C1", "E1"], ["E1", "B1"], ["E1", "B2"], ["E1", "B3"]]
    if with_h2:
        eq[0]["level0"], eq[0]["levelCommodity"] = 30, "YM"
        eq.append({"id": "H2", "type": "hopper", "name": "Hopper 2", "capT": 60, "rate": 400, "tip": [1, 1, 1],
                   "commodities": ["YM"], "level0": 30, "levelCommodity": "YM"})
        edges.append(["H2", "C1"])
    raw = {"id": "t", "name": "Test silo", "version": 1, "hours": {"open": 7, "close": 18},
           "commodities": [{"id": "YM", "name": "Yellow maize"}, {"id": "WM", "name": "White maize"},
                           {"id": "SB", "name": "Soybeans"}],
           "equipment": eq, "edges": edges, "sequences": {"unload": ["tip"]}, "demand": {}}
    if changeovers is not None:
        raw["changeovers"] = changeovers
    return load_site_config(raw)


def trucks(first, second):
    return load_arrival_script({"trucks": [
        {"id": "T1", "activity": "unload", "arrive": "07:00", "commodity": first, "tonnes": 30},
        {"id": "T2", "activity": "unload", "arrive": "07:00", "commodity": second, "tonnes": 30}]})


TIMES = FixedServiceTimes({"tip": 1})


def run(s, first="YM", second="WM"):
    result = TruckFlowModel(s, trucks(first, second), TIMES, policy="feasible_first").run()
    assert result.material_balance_kg == 0 and result.violations == []
    return result


def second_transfer(result):
    x = result.transfers[1]
    return x.started, x.flow_started, x.finished, x.changeover_segments


# ---------------- matrix lookups ----------------

def matrix(changeovers, types=None):
    return ChangeoverMatrix.from_site(site(changeovers))


def test_asymmetric_pair_rules():
    mx = matrix({"rules": [{"from": "YM", "to": "WM", "minutes": 10}, {"from": "WM", "to": "YM", "minutes": 0}]})
    assert mx.required_minutes("E1", YM, WM) == Decimal(10)
    assert mx.required_minutes("E1", WM, YM) == Decimal(0)
    assert mx.required_minutes("E1", YM, YM) == Decimal(0)  # no change of grain
    assert mx.required_minutes("E1", YM, SB) is None  # no rule and no default


def test_most_specific_rule_wins_id_over_type_over_any():
    mx = matrix({"rules": [{"from": "YM", "to": "WM", "minutes": 10},
                           {"from": "YM", "to": "WM", "minutes": 6, "equipment": ["conveyor"]},
                           {"from": "YM", "to": "WM", "minutes": 4, "equipment": ["E1"]}]})
    assert mx.required_minutes("C1", YM, WM) == Decimal(6)  # type rule beats '*'
    assert mx.required_minutes("E1", YM, WM) == Decimal(4)  # id rule beats '*'


def test_default_applies_only_where_no_rule_matches():
    mx = matrix({"default_minutes": 5, "rules": [{"from": "YM", "to": "WM", "minutes": 10}]})
    assert mx.required_minutes("E1", YM, WM) == Decimal(10)
    assert mx.required_minutes("E1", WM, YM) == Decimal(5)


def test_grade_change_needs_a_changeover_only_when_a_grade_rule_says_so():
    ym1, ym2 = GradedCommodity("YM", "1"), GradedCommodity("YM", "2")
    assert matrix({"default_minutes": 5}).required_minutes("E1", ym1, ym2) == Decimal(0)
    mx = matrix({"rules": [{"from": "YM:1", "to": "YM:2", "minutes": 4}]})
    assert mx.required_minutes("E1", ym1, ym2) == Decimal(4)
    assert mx.required_minutes("E1", ym2, ym1) == Decimal(0)


def test_equally_specific_rules_that_disagree_are_ambiguous():
    mx = matrix({"rules": [{"from": "YM", "to": "WM", "minutes": 10}, {"from": "YM", "to": "WM", "minutes": 4}]})
    with pytest.raises(AmbiguousRule):
        mx.required_minutes("E1", YM, WM)


def test_prototype_format_uses_each_equipment_changeover_for_any_commodity_change():
    mx = ChangeoverMatrix.from_site(site(None, c1_extra={"changeover": 6}, e1_extra={"changeover": 8}))
    assert mx.required_minutes("C1", YM, WM) == Decimal(6)
    assert mx.required_minutes("E1", WM, YM) == Decimal(8)


# ---------------- configuration validation ----------------

def messages(issues):
    return [i.msg for i in issues]


def test_missing_pair_is_a_configuration_error_naming_pair_and_equipment():
    """T3.2: only yellow -> white is configured; white -> yellow can happen on C1 and E1."""
    result = validate_rules(site({"rules": [{"from": "YM", "to": "WM", "minutes": 10}]}))
    assert messages(result.errors) == [
        "No changeover rule for White maize → Yellow maize on Pit conveyor.",
        "No changeover rule for White maize → Yellow maize on Elevator 1.",
    ]
    assert [i.ids for i in result.errors] == [["C1"], ["E1"]]


def test_only_pairs_that_can_meet_are_required():
    # Soybeans are a site commodity but H1 does not accept them, so no soybean pair can meet on C1/E1.
    result = validate_rules(site({"rules": [{"from": "YM", "to": "WM", "minutes": 10},
                                            {"from": "WM", "to": "YM", "minutes": 0}]}))
    assert result.errors == [] and result.warnings == []


def test_unknown_references_and_disagreeing_rules_are_errors():
    result = validate_rules(site({"default_minutes": 0, "rules": [
        {"from": "XX", "to": "WM", "minutes": 1},
        {"from": "YM", "to": "WM", "minutes": 1, "equipment": ["ZZ"]},
        {"from": "YM", "to": "WM", "minutes": 10, "equipment": ["E1"]},
        {"from": "YM", "to": "WM", "minutes": 4, "equipment": ["E1"]}]}))
    assert messages(result.errors) == [
        "A changeover rule refers to unknown commodity XX.",
        "A changeover rule refers to unknown equipment ZZ.",
        "Changeover rules for Yellow maize → White maize on Elevator 1 disagree (10 and 4 min).",
    ]


def test_prototype_format_is_accepted_with_a_visible_warning():
    result = validate_rules(site(None, c1_extra={"changeover": 6}, e1_extra={"changeover": 8}))
    assert result.errors == []
    assert messages(result.warnings) == [
        "Changeover times come from each conveyor's and elevator's single changeover value (prototype format) and "
        "apply to any change of commodity. Commodity-pair changeover rules are not configured."]


def test_model_refuses_a_site_with_missing_changeover_rules():
    with pytest.raises(ModelError, match="No changeover rule for White maize"):
        TruckFlowModel(site({"rules": [{"from": "YM", "to": "WM", "minutes": 10}]}), trucks("YM", "WM"), TIMES,
                       policy="feasible_first")


# ---------------- timing in the running model ----------------

def test_asymmetric_changeover_delays_the_transfer():
    """T3.1: yellow then white maize, rule YM->WM 10 min. T2's lot reserved 07:11, flows 07:21-07:30 (10 + 9 = 19)."""
    rules = {"rules": [{"from": "YM", "to": "WM", "minutes": 10}, {"from": "WM", "to": "YM", "minutes": 0}]}
    result = run(site(rules), "YM", "WM")
    assert second_transfer(result) == (hm("07:11"), hm("07:21"), hm("07:30"), {"C1": 600_000, "E1": 600_000})
    assert result.changeovers == {"C1": 1, "E1": 1}


def test_zero_minute_changeover_is_recorded_without_delay():
    """White then yellow maize, rule WM->YM 0 min: T2's lot flows 07:11-07:20; the changeover is still counted."""
    rules = {"rules": [{"from": "YM", "to": "WM", "minutes": 10}, {"from": "WM", "to": "YM", "minutes": 0}]}
    result = run(site(rules), "WM", "YM")
    assert second_transfer(result) == (hm("07:11"), hm("07:11"), hm("07:20"), {"C1": 0, "E1": 0})


def test_segments_change_over_in_parallel_so_the_longest_wins():
    """T3.3 (A5): conveyor 6 min, elevator 4 min (id rule) -> route waits 6 min: flows 07:17-07:26."""
    rules = {"rules": [{"from": "YM", "to": "WM", "minutes": 10},
                       {"from": "YM", "to": "WM", "minutes": 6, "equipment": ["conveyor"]},
                       {"from": "YM", "to": "WM", "minutes": 4, "equipment": ["E1"]},
                       {"from": "WM", "to": "YM", "minutes": 0}]}
    result = run(site(rules), "YM", "WM")
    assert second_transfer(result) == (hm("07:11"), hm("07:17"), hm("07:26"), {"C1": 360_000, "E1": 240_000})


def test_prototype_format_changeover_in_the_running_model():
    """No pair rules; C1 changeover 6, E1 changeover 8 -> route waits 8 min: flows 07:19-07:28."""
    result = run(site(None, c1_extra={"changeover": 6}, e1_extra={"changeover": 8}), "YM", "WM")
    assert second_transfer(result)[:3] == (hm("07:11"), hm("07:19"), hm("07:28"))


def test_route_is_held_for_the_clear_time_after_the_last_grain():
    """T3.4: E1 clear time 2 min. H1 and H2 each hold 30 t yellow maize and share C1 -> E1.
    H1's lot flows 07:00-07:09 (in the bin at 07:09); the route stays reserved until 07:11;
    H2's lot then flows 07:11-07:20 (released 07:22)."""
    s = site({"default_minutes": 0}, e1_extra={"clear_minutes": 2}, with_h2=True, commodities=("YM",))
    result = TruckFlowModel(s, [], TIMES, policy="feasible_first").run()
    assert result.material_balance_kg == 0 and result.violations == []
    a, b = result.transfers
    assert (a.flow_started, a.finished, a.released) == (hm("07:00"), hm("07:09"), hm("07:11"))
    assert (b.started, b.flow_started, b.finished, b.released) == (hm("07:11"), hm("07:11"), hm("07:20"), hm("07:22"))
