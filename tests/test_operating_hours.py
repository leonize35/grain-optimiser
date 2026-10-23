"""Operating hours, admission cut-off, overtime and unfinished work (R6). Build step 7.

Hours in these tests: open 07:00, admission cut-off 07:45, close 08:00, overtime 30 min (hard stop 08:30).
- The gate admits trucks from opening until the cut-off.
- Services may start until the hard stop; a service already running then is completed (A7).
- Unfinished trucks carry over (default) or are sent away; they are always reported.
"""
import copy

import pytest

from silo_engine.config import load_site_config
from silo_engine.config.rules_validation import validate_rules
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import MS_PER_DAY, hm, m
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel

DAY2 = MS_PER_DAY

WEIGH_SITE = {
    "id": "h", "name": "Hours silo", "version": 1,
    "hours": {"open": 7, "admission_cutoff": 7.75, "close": 8, "overtime": 0.5},
    "commodities": [{"id": "YM", "name": "Yellow maize"}],
    "equipment": [{"id": "WB1", "type": "weighbridge", "name": "Weighbridge", "cap": 1, "time": [10, 10, 10]}],
    "edges": [], "sequences": {"weigh": ["weigh_in"]}, "demand": {},
}


def raw(base=WEIGH_SITE, **changes):
    r = copy.deepcopy(base)
    r.update(changes)
    return r


def weigh_trucks(*rows):
    return load_arrival_script({"trucks": [
        {"id": tid, "activity": "weigh", "arrive": at, **({"day": day} if day != 1 else {})} for tid, at, day in rows]})


def run(r, trucks, minutes=10, days=1):
    model = TruckFlowModel(load_site_config(r), trucks, FixedServiceTimes({"weigh_in": minutes, "tip": 10}),
                           policy="feasible_first", days=days)
    result = model.run()
    assert result.material_balance_kg == 0 and result.violations == [] and result.stall is None
    return result


def rec(result, tid):
    return next(x for x in result.records if x.truck_id == tid)


def started(result, tid, step="weigh_in"):
    return next(s for s in rec(result, tid).steps if s.step == step).started


SIX = [(f"T{i}", "07:40", 1) for i in range(1, 7)]


def test_early_arrival_waits_at_the_gate_until_opening():
    """Arrives 06:50; admitted at 07:00; weighed 07:00-07:10. Turnaround counts from arrival: 20 min."""
    result = run(raw(), weigh_trucks(("T1", "06:50", 1)))
    assert started(result, "T1") == hm("07:00")
    assert rec(result, "T1").departed - rec(result, "T1").arrived == m(20)


def test_overtime_serves_admitted_trucks_until_the_hard_stop():
    """T6.1: six trucks at 07:40, 10 min each: T1 07:40, T2 07:50 ... T5 08:20-08:30. T6 would start at 08:30,
    the hard stop, so it is unfinished and reported with 50 min waiting (07:40 to 08:30).
    Completed turnarounds 10, 20, 30, 40, 50 min: mean 30. Including T6 as a lower bound: (150 + 50) / 6."""
    result = run(raw(), weigh_trucks(*SIX))
    assert [started(result, f"T{i}") for i in range(1, 6)] == [hm(x) for x in ("07:40", "07:50", "08:00", "08:10", "08:20")]
    assert [(u.truck_id, u.step, u.admitted) for u in result.unfinished] == [("T6", "weigh_in", True)]
    s = result.summary["weigh"]
    assert (s.completed, s.unfinished, s.turned_away) == (5, 1, 0)
    assert s.mean_turnaround_min == 30
    assert s.unfinished_waiting_min == [50]
    assert s.mean_turnaround_incl_unfinished_min == pytest.approx(200 / 6)


def test_unfinished_truck_carries_over_to_the_next_day():
    """T6.2: two-day run. T6 stays on site overnight and is weighed on day 2 at 07:00-07:10.
    Turnaround from its arrival (day 1 07:40) to departure (day 2 07:10): 23 h 30 min = 1410 min."""
    result = run(raw(), weigh_trucks(*SIX), days=2)
    assert started(result, "T6") == DAY2 + hm("07:00")
    assert rec(result, "T6").departed - rec(result, "T6").arrived == m(1410)
    assert result.unfinished == [] and result.summary["weigh"].completed == 6


def test_unfinished_trucks_can_be_sent_away_at_the_hard_stop():
    """unfinished_trucks = turned_away, 12 min weighing: T1 07:40, T2 07:52, T3 08:04, T4 08:16, T5 08:28.
    T5 is being weighed at the hard stop: its service is completed (08:40). T6 has not started and is sent away
    at 08:30."""
    r = raw(end_of_day={"unfinished_trucks": "turned_away"})
    result = run(r, weigh_trucks(*SIX), minutes=12)
    assert rec(result, "T5").departed == hm("08:40")
    assert rec(result, "T6").turned_away == "still on site when service stopped"
    assert rec(result, "T6").departed is None
    assert result.unfinished == []
    assert result.summary["weigh"].turned_away == 1


def test_late_arrival_queues_for_the_next_day():
    """Arrives 07:50, after the 07:45 cut-off: admitted on day 2 at 07:00, weighed 07:00-07:10.
    Turnaround: day 1 07:50 to day 2 07:10 = 23 h 20 min = 1400 min."""
    result = run(raw(), weigh_trucks(("T1", "07:50", 1)), days=2)
    assert started(result, "T1") == DAY2 + hm("07:00")
    assert rec(result, "T1").departed - rec(result, "T1").arrived == m(1400)


def test_late_arrival_can_be_turned_away():
    r = raw(end_of_day={"late_arrivals": "turned_away"})
    result = run(r, weigh_trucks(("T1", "07:50", 1), ("T2", "07:44", 1)))
    assert rec(result, "T1").turned_away == "arrived after the admission cut-off"
    assert rec(result, "T1").steps == []
    assert started(result, "T2") == hm("07:44")


def test_late_arrival_on_the_last_day_is_reported_as_not_admitted():
    result = run(raw(), weigh_trucks(("T1", "07:50", 1)))
    assert [(u.truck_id, u.admitted) for u in result.unfinished] == [("T1", False)]
    assert result.summary["weigh"].unfinished_waiting_min == [40]  # 07:50 to the 08:30 hard stop


# Grain after close: hopper (100 t pit, tipping 10 min) -> C1 -> E1 (100 t/h) -> B1. 30 t lots take 18 min.
# T1..T3 arrive 07:44: tips 07:44-07:54, 07:54-08:04, 08:04-08:14. Lots flow 07:54-08:12, 08:12-08:30, then
# the third lot is ready to start at 08:30, the hard stop.
GRAIN_SITE = raw(
    equipment=[{"id": "H1", "type": "hopper", "name": "Hopper 1", "capT": 100, "rate": 400, "tip": [10, 10, 10],
                "commodities": ["YM"]},
               {"id": "C1", "type": "conveyor", "name": "C1", "rate": 300},
               {"id": "E1", "type": "elevator", "name": "E1", "rate": 100},
               {"id": "B1", "type": "bin", "name": "Bin 1", "capT": 1000, "commodities": ["YM"]}],
    edges=[["H1", "C1"], ["C1", "E1"], ["E1", "B1"]], sequences={"unload": ["tip"]})
GRAIN_TRUCKS = [{"id": f"T{i}", "activity": "unload", "arrive": "07:44", "commodity": "YM", "tonnes": 30} for i in (1, 2, 3)]


def flows(result):
    return [(x.flow_started, x.finished) for x in result.transfers]


def test_grain_keeps_moving_after_close_by_default():
    result = run(GRAIN_SITE, load_arrival_script({"trucks": GRAIN_TRUCKS}))
    assert flows(result) == [(hm("07:54"), hm("08:12")), (hm("08:12"), hm("08:30")), (hm("08:30"), hm("08:48"))]
    assert result.pits == {"H1": 0}


def test_grain_waits_for_the_next_day_when_transfers_stop_at_close():
    r = raw(GRAIN_SITE, end_of_day={"transfers_after_close": False})
    one_day = run(r, load_arrival_script({"trucks": GRAIN_TRUCKS}))
    assert len(one_day.transfers) == 2 and one_day.pits == {"H1": 30_000}
    two_days = run(r, load_arrival_script({"trucks": GRAIN_TRUCKS}), days=2)
    assert flows(two_days)[2] == (DAY2 + hm("07:00"), DAY2 + hm("07:18"))


def test_waiting_overnight_is_not_a_stall_but_is_explained():
    model = TruckFlowModel(load_site_config(raw()), weigh_trucks(*SIX), FixedServiceTimes({"weigh_in": 10}),
                           policy="feasible_first", days=2)
    model.run(until=hm("09:00"))
    assert model.stall is None
    assert [r.code for r in model.waiting_reasons()["T6/weigh_in"]] == ["PLANT_CLOSED"]


def test_truck_arriving_after_the_last_simulated_day_is_refused():
    with pytest.raises(ModelError, match="day 3"):
        TruckFlowModel(load_site_config(raw()), weigh_trucks(("T1", "07:10", 3)), FixedServiceTimes({"weigh_in": 10}),
                       policy="feasible_first", days=2)


def test_hours_must_be_consistent():
    r = raw(hours={"open": 7, "admission_cutoff": 8.5, "close": 8, "overtime": 0.5})
    assert [i.msg for i in validate_rules(load_site_config(r)).errors] == [
        "The admission cut-off (08:30) must be between opening (07:00) and closing (08:00)."]
    r = raw(hours={"open": 9, "close": 8})
    assert [i.msg for i in validate_rules(load_site_config(r)).errors] == [
        "Opening time (09:00) must be before closing time (08:00)."]


def test_default_end_of_day_rules_are_listed_as_assumptions():
    result = run(raw(), weigh_trucks(("T1", "07:10", 1)))
    assert "Unfinished trucks stay on site and continue the next operating day (default)." in result.assumptions
    assert "Grain transfers continue after closing until the pits are empty (default)." in result.assumptions
