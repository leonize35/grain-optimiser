"""TLS slice T1 (docs/TLS_ANALYSIS_DESIGN.md §3, §4): resource use report and Little's law check. Hand-traced.
Analysis only: computed from a finished run's records; the simulation is unchanged.

Site and trucks of tests/test_outcomes_clearance.py (test inputs): open 07:00, hard stop 07:54 (54 open minutes).
WB_IN (1 lane): T5 07:00-02, T1 07:02-04 (queued 07:00-02), T2 07:10-12, T3 07:17-19 -> busy 8 min, queued 2.
H1 (one tipping lane): T5 07:02-07, T1 07:07-12 (queued 07:04-07), T2 07:12-17, T3 07:19-24 -> busy 20, queued 3.
WB_OUT: T5 07:07-09, T1 07:12-14, T2 07:17-19, T3 07:24-26 -> busy 8 (07:24-26 is after closing, before the stop).
Intake C1, E1: four 1-minute transfers (07:07, 07:12, 07:17, 07:24) -> 4 min reserved and flowing.
Gate: T5 waits 06:50-07:00 (before opening); T4 arrives 07:25 after the cut-off and is still held at 07:54 (29 min,
censored). Truck-minutes on site 80 over the window 06:50-07:54 (64 min).
"""
import copy

import pytest

from silo_engine.analysis.resource_use import resource_use
from silo_engine.config import load_site_config
from test_custom_steps import raw as docs_raw, run as docs_run
from test_outcomes_clearance import RAW, run


def report(**kw):
    return resource_use(load_site_config(copy.deepcopy(RAW)), run(), **kw)


def test_station_and_hopper_use():
    r = report()
    assert r["window"] == {"start": 7 * 3600000, "end": 7 * 3600000 + 54 * 60000, "open_minutes": 54}
    eq = r["equipment"]
    assert {k: (v["kind"], v["lanes"], v["busy_min"], v["blocked_min"], v["queued_truck_min"], v["served"])
            for k, v in eq.items()} == {
        "WB_IN": ("station", 1, 8, 0, 2, 4), "H1": ("hopper", 1, 20, 0, 3, 4), "WB_OUT": ("station", 1, 8, 0, 0, 4)}
    assert eq["H1"]["utilisation"] == pytest.approx(20 / 54)
    assert eq["WB_IN"]["mean_queue"] == pytest.approx(2 / 54)  # time-average trucks queued for it, over open time
    assert eq["WB_OUT"]["busy_after_hours_min"] == 0


def test_grain_route_use():
    seg = report()["segments"]
    assert {k: (v["type"], v["reserved_min"], v["flowing_min"]) for k, v in seg.items()} == {
        "C1": ("conveyor", 4, 4), "E1": ("elevator", 4, 4)}
    assert seg["E1"]["utilisation"] == pytest.approx(4 / 54)


def test_gate_waiting_is_reported_with_censoring():
    assert report()["gate"] == {"queued_truck_min": 39, "censored_truck_min": 29, "held_at_end": 1}


def test_blocked_time_at_a_station():
    """A release rule holds T1 at the document station from 07:05 (service done) until 07:12 (test_custom_steps)."""
    task = [{"id": "cleared", "started_by": "weigh_in", "time": [10, 10, 10], "produces": "cleared"}]
    rule = [{"activity": "unload", "step": "documents", "when": ["service_done", "cleared"]}]
    r = docs_raw(background_tasks=task, release_rules=rule)
    use = resource_use(load_site_config(r), docs_run(r, trucks=(("T1", "07:00"),)))
    assert (use["equipment"]["DOCS"]["busy_min"], use["equipment"]["DOCS"]["blocked_min"]) == (3, 7)


def test_littles_law_exact_form_and_steady_state_gap():
    """Exact (censored) form over 06:50-07:54: L = 80/64 = 1.25 trucks; arrival rate 5/64 per min; W = 80/5 = 16 min;
    L = rate x W (independent sources: a sweep of arrivals and exits, and the outcomes' time on site).
    Steady-state reading with completed trucks only: W = (19+14+9+9)/4 = 12.75 min, rate x W = 0.99609375, a gap of
    -20.3 % against L, beyond the 10 % tolerance: the edges of the run (a truck held at the gate) distort the mean."""
    lt = report()["little"]
    assert (lt["window_min"], lt["L"], lt["arrival_rate_per_min"], lt["W_min"]) == (64, 1.25, 5 / 64, 16)
    assert lt["exact_ok"] is True
    assert (lt["W_completed_min"], lt["steady_gap"]) == (12.75, pytest.approx(-0.203125))
    assert (lt["tolerance"], lt["steady_ok"]) == (0.1, False)
    assert report(little_tolerance=0.25)["little"]["steady_ok"] is True


def test_limitations_are_listed():
    lim = " ".join(report()["limitations"])
    assert "partial tipping" in lim and "served" in lim


def test_grader_use_comes_from_its_reservations():
    """Grading is not a truck step: the grader's use is read from the reservation ledger (tests/test_grading_blocking.py
    site: sampler 4 min, one grader 10 min). Samples: T1 07:00-04, T2 07:04-08, T3 07:08-12. Grading: T1 07:04-14,
    T2 07:14-24 (queued from 07:08), T3 07:24-34 (queued from 07:12) -> busy 30 min, queued 6 + 12 = 18."""
    from test_grading_blocking import RAW as GRADING, run as grading_run
    r = grading_run([("T1", "07:00"), ("T2", "07:01"), ("T3", "07:02")])
    g = resource_use(load_site_config(copy.deepcopy(GRADING)), r)["equipment"]["G1"]
    assert (g["kind"], g["busy_min"], g["queued_truck_min"], g["served"]) == ("grader", 30, 18, 3)
