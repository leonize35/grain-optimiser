"""Truck outcomes, time on site, weighbridge instants and daily clearance (docs/MEASUREMENT_FRAMEWORK.md §1, K2, K3,
K6, §4; checklist A1-A4). Hand-traced.

Site (test input, not Ventersdorp data): a dedicated incoming weighbridge WB_IN and outgoing WB_OUT (one truck each,
2 min), one hopper (tip 5 min) draining at 1 800 t/h (a 30 t lot in 1 min). Sequence weigh_in -> tip -> weigh_out;
no truck path (unlimited waiting). Hours: open 07:00, admission cut-off 07:18, close 07:24, overtime 30 min
(hard stop 07:54).

Trucks: T5 06:50 (before opening), T1 07:00, T2 07:10, T3 07:17, T4 07:25 (after the cut-off).
07:00 opening admits T5: WB_IN 07:00-07:02, tip 07:02-07:07, WB_OUT 07:07-07:09, departs 07:09.
T1: WB_IN 07:02-07:04, waits for the hopper, tip 07:07-07:12, WB_OUT 07:12-07:14, departs 07:14.
T2: WB_IN 07:10-07:12, tip 07:12-07:17, WB_OUT 07:17-07:19, departs 07:19.
T3: WB_IN 07:17-07:19, tip 07:19-07:24, WB_OUT 07:24-07:26, departs 07:26 (processed after closing).
T4: held at the gate for the next day (default), still there when the run ends at the hard stop 07:54.
"""
import copy

from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import TruckFlowModel

TIMES = FixedServiceTimes({"weigh_in": 2, "tip": 5, "weigh_out": 2})
TRUCKS = [("T5", "06:50"), ("T1", "07:00"), ("T2", "07:10"), ("T3", "07:17"), ("T4", "07:25")]
RAW = {
    "id": "clearance", "name": "Clearance test site", "version": 1,
    "hours": {"open": 7, "admission_cutoff": 7.3, "close": 7.4, "overtime": 0.5},
    "commodities": [{"id": "YM", "name": "Yellow maize"}],
    "equipment": [
        {"id": "WB_IN", "type": "weighbridge", "name": "Incoming", "cap": 1, "moves": "in", "time": [2, 2, 2]},
        {"id": "WB_OUT", "type": "weighbridge", "name": "Outgoing", "cap": 1, "moves": "out", "time": [2, 2, 2]},
        {"id": "H1", "type": "hopper", "name": "H1", "capT": 60, "rate": 1800, "tip": [5, 5, 5], "commodities": ["YM"]},
        {"id": "C1", "type": "conveyor", "name": "C1", "rate": 1800},
        {"id": "E1", "type": "elevator", "name": "E1", "rate": 1800},
        {"id": "B1", "type": "bin", "name": "B1", "capT": 5000, "commodities": ["YM"]}],
    "edges": [["H1", "C1"], ["C1", "E1"], ["E1", "B1"]],
    "sequences": {"unload": ["weigh_in", "tip", "weigh_out"]}, "demand": {}, "changeovers": {"default_minutes": 0}}


def run(**changes):
    raw = copy.deepcopy(RAW)
    for k, v in changes.items():
        raw[k] = {**raw.get(k, {}), **v} if isinstance(v, dict) else v
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": 30} for t, at in TRUCKS]})
    r = TruckFlowModel(load_site_config(raw), script, TIMES, policy="feasible_first").run()
    assert r.violations == [] and r.material_balance_kg == 0 and r.stall is None
    return r


def test_each_truck_has_exactly_one_outcome():
    o = run().outcomes
    assert {t: x["status"] for t, x in o["trucks"].items()} == {
        "T5": "completed", "T1": "completed", "T2": "completed", "T3": "completed", "T4": "unfinished_at_gate"}
    assert o["summary"]["unload"]["counts"] == {"completed": 4, "unfinished_on_site": 0, "unfinished_at_gate": 1,
                                                "turned_away": 0, "total": 5}


def test_time_on_site_and_truck_hours():
    """Time on site (min): T5 19 (10 at the gate before opening), T1 14, T2 9, T3 9, T4 29 at the gate (censored at
    the hard stop). Truck-minutes 80 = gate 39 + site 41; mean observed time on site 80 / 5 = 16."""
    o = run().outcomes
    assert {t: (x["time_on_site_min"], x["gate_min"], x["censored"]) for t, x in o["trucks"].items()} == {
        "T5": (19, 10, False), "T1": (14, 0, False), "T2": (9, 0, False), "T3": (9, 0, False), "T4": (29, 29, True)}
    occ = o["summary"]["unload"]["occupancy"]
    assert (occ["truck_minutes"], occ["gate_minutes"], occ["site_minutes"], occ["mean_observed_time_on_site_min"]) == \
        (80, 39, 41, 16)


def test_truck_minutes_equal_the_integral_of_trucks_present():
    """K6 identity: the sum of each truck's time on site within the horizon equals the integral of the number of
    trucks present (computed here independently by sweeping the arrival and exit instants)."""
    r = run()
    trucks = r.outcomes["trucks"]
    end = hm("07:54")
    events = sorted([(x["arrived"], 1) for x in trucks.values()] +
                    [(min(x["exit"] if x["exit"] is not None else end, end), -1) for x in trucks.values()])
    integral, present, last = 0, 0, None
    for t, d in events:
        if last is not None:
            integral += present * (t - last)
        present, last = present + d, t
    assert integral / 60000 == r.outcomes["summary"]["unload"]["occupancy"]["truck_minutes"]


def test_weighbridge_instants_per_truck():
    t1 = run().outcomes["trucks"]["T1"]["weighbridge"]
    assert t1 == {"weigh_in_start": hm("07:02"), "weigh_in_end": hm("07:04"),
                  "weigh_out_start": hm("07:12"), "weigh_out_end": hm("07:14")}
    assert run().outcomes["trucks"]["T4"]["weighbridge"] == {
        "weigh_in_start": None, "weigh_in_end": None, "weigh_out_start": None, "weigh_out_end": None}


def test_closing_continued_processing_and_final_clearance():
    """Admission closes 07:18; closing 07:24; T3 (admitted 07:17) is still on site at closing and departs 07:26:
    final clearance 07:26, 2 min after closing, before the hard stop. T4 was not admitted."""
    day = run().clearance[0]
    assert day == {"day": 1, "opens": hm("07:00"), "admission_cutoff": hm("07:18"), "close": hm("07:24"),
                   "hard_stop": hm("07:54"), "admitted": 4, "last_admission": hm("07:17"),
                   "on_site_at_close": 1, "final_clearance": hm("07:26"), "cleared": True,
                   "overtime_used_min": 2.0, "after_hard_stop": False, "remaining": [], "held_at_gate": 1}


def test_not_cleared_when_service_stops_at_closing():
    """No overtime: the hard stop is 07:24. T3 finishes tipping at 07:24 and may not start weighing out at the stop,
    so it is still on site: not cleared, no clearance time."""
    day = run(hours={"overtime": 0}).clearance[0]
    assert (day["cleared"], day["final_clearance"], day["overtime_used_min"], day["remaining"]) == \
        (False, None, None, ["T3"])
    assert run(hours={"overtime": 0}).outcomes["trucks"]["T3"]["status"] == "unfinished_on_site"


def test_turned_away_is_a_separate_outcome():
    """Late arrivals turned away: T4 leaves at 07:25 with its reason; it is not a completion and has no turnaround."""
    r = run(end_of_day={"late_arrivals": "turned_away"})
    t4 = r.outcomes["trucks"]["T4"]
    assert (t4["status"], t4["reason"], t4["time_on_site_min"], t4["exit"]) == \
        ("turned_away", "arrived after the admission cut-off", 0, hm("07:25"))
    s = r.outcomes["summary"]["unload"]
    assert s["counts"]["turned_away"] == 1 and s["counts"]["completed"] == 4
    assert s["turned_away"] == {"arrived after the admission cut-off": {"count": 1, "mean_time_on_site_min": 0,
                                                                        "max_time_on_site_min": 0}}
    assert r.summary["unload"].mean_turnaround_min == (19 + 14 + 9 + 9) / 4  # completed trucks only, unchanged


# ---- A5: restricted mean time to completion on the full-follow-up cohort (MEASUREMENT_FRAMEWORK K7) ----
def test_rmst_cohort_hand_values():
    """Horizon end H = 07:54. Times to completion (min): T5 19, T1 14, T2 9, T3 9; T4 never completes.
    tau 10: cohort = arrivals <= 07:44 = all 5; X = 10, 10, 9, 9, 10 -> 9.6; completed within tau: T2, T3 (2/5).
    tau 20: all 5; X = 19, 14, 9, 9, 20 -> 14.2; F_C = 4/5.
    tau 40: cohort = arrivals <= 07:14: T5, T1, T2 -> X = 19, 14, 9 -> 14 = their completed mean (consistency);
    T3 and T4 are outside the cohort."""
    from silo_engine.sim.outcomes import restricted_mean_time_to_completion as rmst
    o = run().outcomes
    a = rmst(o, 10)
    assert (a["cohort"], a["outside_cohort"], a["rmst_min"], a["completed_within_tau"], a["turned_away_within_tau"]) == \
        (5, 0, 9.6, 0.4, 0.0)
    assert (rmst(o, 20)["rmst_min"], rmst(o, 20)["completed_within_tau"]) == (14.2, 0.8)
    c = rmst(o, 40)
    assert (c["cohort"], c["outside_cohort"], c["rmst_min"]) == (3, 2, 14)


def test_rmst_counts_a_turned_away_truck_as_not_completed():
    """T4 turned away at arrival: X = tau (never completes); tau 20 -> (19 + 14 + 9 + 9 + 20) / 5 = 14.2, F_R = 1/5.
    The completed-only mean is unchanged (12.75); the RMST does not reward sending a truck away."""
    from silo_engine.sim.outcomes import restricted_mean_time_to_completion as rmst
    r = run(end_of_day={"late_arrivals": "turned_away"})
    x = rmst(r.outcomes, 20)
    assert (x["rmst_min"], x["completed_within_tau"], x["turned_away_within_tau"]) == (14.2, 0.8, 0.2)


def test_rmst_needs_a_positive_tau_and_reports_an_empty_cohort():
    import pytest
    from silo_engine.sim.outcomes import restricted_mean_time_to_completion as rmst
    o = run().outcomes
    with pytest.raises(ValueError):
        rmst(o, 0)
    e = rmst(o, 600)  # no arrival is 10 h before the horizon end
    assert (e["cohort"], e["rmst_min"]) == (0, None)


# ---- A10: tonnes consistency (K4) and commodity fairness bounds (K8) ----
def test_tonnes_received_completed_and_in_progress():
    """Base day: T5, T1, T2, T3 tip and depart: 120 t received = 120 t of completed trucks, nothing in progress.
    No overtime: T3 finishes tipping at 07:24 but cannot weigh out: 120 t received, 90 t completed, 30 t in
    progress. Received tonnes equal the engine's received_kg (grain balance)."""
    for changes, completed, progress in (({}, 120, 0), ({"hours": {"overtime": 0}}, 90, 30)):
        r = run(**changes)
        t = r.outcomes["summary"]["unload"]["tonnes"]
        assert (t["received_t"], t["completed_trucks_t"], t["in_progress_t"]) == (120, completed, progress)
        assert t["received_t"] * 1000 == r.received_kg


def test_starvation_bounds_include_censored_trucks_in_the_upper_bound():
    """Threshold 30 min. Waits: T5 10, T1 5, T2 0, T3 0 (completed); T4 29 so far, censored (still at the gate).
    Lower bound 0 (T4 not starved yet); upper bound 1 (T4 might reach 30). Completion rate 4/5."""
    r = run(fairness={"starvation_wait_minutes": 30})
    f = r.outcomes["fairness"]["unload"]["YM"]
    assert (f["trucks"], f["completion_rate"], f["starved_lower"], f["starved_upper"]) == (5, 0.8, 0, 1)


def test_commodity_disparity():
    """YM: two completed (waits 10, 50). WM: one completed (5), one unfinished (20 so far), one turned away.
    Threshold 30: YM starved [1, 1]; WM [0, 1]. Completion YM 1.0, WM 1/3: spread 2/3, ratio 1/3."""
    from types import SimpleNamespace as M
    from silo_engine.sim.outcomes import commodity_fairness

    def m(c, status, wait, censored=False):
        return M(activity="unload", commodity=c, status=status, total_waiting_min=wait, wait_censored=censored,
                 starved=wait >= 30, overtaken_by_later=0)
    metrics = [m("YM", "completed", 10), m("YM", "completed", 50), m("WM", "completed", 5),
               m("WM", "unfinished", 20, True), m("WM", "turned_away", 0)]
    f = commodity_fairness(metrics)
    assert (f["unload"]["YM"]["starved_lower"], f["unload"]["YM"]["starved_upper"]) == (1, 1)
    assert (f["unload"]["WM"]["starved_lower"], f["unload"]["WM"]["starved_upper"]) == (0, 1)
    d = f["disparity"]["unload"]["completion_rate"]
    assert (d["spread"], d["ratio"]) == (1 - 1 / 3, 1 / 3)
