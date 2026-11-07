"""TLS slice T3 (docs/TLS_ANALYSIS_DESIGN.md §4): value-stream map. Hand-traced; test inputs. Analysis only.

The site classifies its own steps (value_adding, necessary, waste); there is no default, and unclassified steps
are reported as such. Site and trucks of tests/test_outcomes_clearance.py; completed trucks T5, T1, T2, T3:
T5 gate 10 (06:50-07:00), weigh_in 2, tip 5, weigh_out 2 -> 19 min on site.
T1 weigh_in wait 2 + 2, tip wait 3 + 5, weigh_out 2 -> 14.   T2, T3: 2 + 5 + 2 -> 9 each.
Means over the 4: gate 2.5; weigh_in wait 0.5, service 2; tip wait 0.75, service 5; weigh_out 2; lead time 12.75.
"""
import copy

import pytest

from silo_engine.analysis.value_stream import value_stream
from silo_engine.config import load_site_config
from test_outcomes_clearance import RAW, run

CLASSES = {"tip": "value_adding", "weigh_in": "necessary", "weigh_out": "necessary"}


def vsm(classes=CLASSES):
    return value_stream(load_site_config(copy.deepcopy(RAW)), run(), classes)


def test_steps_in_the_site_sequence_with_wait_service_and_class():
    m = vsm()
    assert [(s["step"], s["class"], s["trucks"], s["mean_wait_min"], s["mean_service_min"], s["mean_blocked_min"],
             s["mean_move_min"]) for s in m["steps"]] == [
        ("weigh_in", "necessary", 4, 0.5, 2, 0, 0), ("tip", "value_adding", 4, 0.75, 5, 0, 0),
        ("weigh_out", "necessary", 4, 0, 2, 0, 0)]
    assert (m["completed_trucks"], m["mean_gate_min"], m["mean_lead_time_min"]) == (4, 2.5, 12.75)


def test_lead_time_breakdown_adds_up_and_gives_process_cycle_efficiency():
    m = vsm()
    b = m["breakdown_min"]
    assert b == {"value_adding": 5, "necessary": 4, "waste": 0, "unclassified": 0, "waiting": 3.75, "moving": 0}
    assert sum(b.values()) == m["mean_lead_time_min"]  # independent check (every truck's parts add up)
    assert m["adds_up"] is True
    assert m["process_cycle_efficiency"] == pytest.approx(5 / 12.75)


def test_unclassified_steps_are_reported_and_efficiency_is_not_given():
    m = vsm({"tip": "value_adding"})
    assert [s["class"] for s in m["steps"]] == ["unclassified", "value_adding", "unclassified"]
    assert m["breakdown_min"]["unclassified"] == 4
    assert m["process_cycle_efficiency"] is None and "unclassified" in m["notes"][0]


def test_takt_time_against_step_cycle_times():
    """Open time 54 min (07:00-07:54), 5 receiving trucks arrived: takt 10.8 min per truck. Cycle time of a step:
    mean service / lanes that served it: weigh_in 2, tip 5, weigh_out 2; none slower than takt."""
    m = vsm()
    assert m["takt_min"] == pytest.approx(10.8)
    assert {s["step"]: (s["lanes"], s["cycle_min"], s["slower_than_takt"]) for s in m["steps"]} == {
        "weigh_in": (1, 2, False), "tip": (1, 5, False), "weigh_out": (1, 2, False)}


def test_waste_view():
    """All trucks (censored included): waiting 44 truck-min (gate 10 + 29, queues 2 + 3), moving between places,
    unfinished and turned-away trucks, trucks on
    site on average (Little's L: 80 truck-min / 64 min) and grain in pits (30 t lots, tipping to storage)."""
    w = vsm()["waste"]
    assert (w["waiting_truck_min"], w["moving_truck_min"], w["unfinished_trucks"], w["turned_away_trucks"]) == (
        44, 0, 1, 0)
    assert w["mean_trucks_on_site"] == 1.25
    assert w["mean_tipping_to_storage_min"] == 1  # each lot drains in 1 min after tipping
    assert "rework" in " ".join(w["not_modelled"])


def test_invalid_class_is_refused():
    with pytest.raises(ValueError, match="value_adding, necessary or waste"):
        vsm({"tip": "useful"})


def test_waiting_during_partial_tipping_is_not_service():
    """tests/test_partial_tipping.py: tipping 07:00-07:17:45 of which 10 min tipping and 7.75 min waiting for space."""
    from test_partial_tipping import RAW as P, run as prun
    m = value_stream(load_site_config(copy.deepcopy(P)), prun(copy.deepcopy(P)), {"tip": "value_adding"})
    tip = m["steps"][0]
    assert (tip["mean_service_min"], tip["mean_held_in_service_min"]) == (10, 7.75)
    assert m["breakdown_min"]["value_adding"] == 10 and m["breakdown_min"]["waiting"] == 7.75
    assert m["adds_up"] is True
