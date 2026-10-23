"""Fairness and starvation reporting (Q1: report only; queue-selection policies are unchanged).

Per truck: total waiting time, times overtaken by later-arriving trucks, unfinished at the end. Per activity and
commodity: waits and turnaround. Starved trucks are counted against a configurable threshold.

Hand-traced case. One hopper H1 (yellow and white maize) -> C1 -> E1 (200 t/h) -> B1 (yellow) / B2 (white);
tipping 1 min; 30 t lots flow 9 min; feasible-first. Three trucks arrive at 07:00, in this order:
  Y1 (yellow) tips 07:00-07:01 and leaves; its lot flows 07:01-07:10.
  W1 (white) cannot tip onto yellow grain: it waits.
  Y2 (yellow, arrived after W1) overtakes W1: tips 07:01-07:02 (lane busy until 07:01); its lot flows 07:10-07:19.
  The pit is empty at 07:19: W1 tips 07:19-07:20.
Total waiting (time on site not in service): Y1 0 min, Y2 1 min, W1 19 min. W1 was overtaken once, by Y2.
"""
import copy
import json
from pathlib import Path

from silo_engine.config import load_site_config
from silo_engine.experiments.runner import kpis_of, run_experiment
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import TruckFlowModel

SITE = {
    "id": "f", "name": "Fairness silo", "version": 1, "hours": {"open": 7, "close": 18},
    "commodities": [{"id": "YM", "name": "Yellow maize"}, {"id": "WM", "name": "White maize"}],
    "equipment": [
        {"id": "H1", "type": "hopper", "name": "Hopper 1", "capT": 60, "rate": 400, "tip": [1, 1, 1], "commodities": ["YM", "WM"]},
        {"id": "C1", "type": "conveyor", "name": "C1", "rate": 300},
        {"id": "E1", "type": "elevator", "name": "E1", "rate": 200},
        {"id": "B1", "type": "bin", "name": "B1", "capT": 1000, "commodities": ["YM"]},
        {"id": "B2", "type": "bin", "name": "B2", "capT": 1000, "commodities": ["WM"]},
    ],
    "edges": [["H1", "C1"], ["C1", "E1"], ["E1", "B1"], ["E1", "B2"]],
    "sequences": {"unload": ["tip"]}, "demand": {}, "changeovers": {"default_minutes": 0},
}


def run(until=None, **changes):
    raw = copy.deepcopy(SITE)
    raw.update(changes)
    trucks = load_arrival_script({"trucks": [
        {"id": tid, "activity": "unload", "arrive": "07:00", "commodity": c, "tonnes": 30}
        for tid, c in (("Y1", "YM"), ("W1", "WM"), ("Y2", "YM"))]})
    model = TruckFlowModel(load_site_config(raw), trucks, FixedServiceTimes({"tip": 1}), policy="feasible_first")
    return model.run(until)


def test_each_truck_records_waiting_overtakes_and_completion():
    result = run()
    m = {t: (x.total_waiting_min, x.overtaken_by_later, x.unfinished) for t, x in result.truck_metrics.items()}
    assert m == {"Y1": (0, 0, False), "W1": (19, 1, False), "Y2": (1, 0, False)}


def test_total_waiting_includes_the_gate_and_every_queue_not_just_the_hopper():
    """Weighbridge (2 min) before the hopper. T1 arrives 06:50, before opening: waits at the gate until 07:00,
    weighs 07:00-07:02, tips 07:02-07:03. T2 arrives 07:00: waits for the weighbridge until 07:02, weighs
    07:02-07:04, tips 07:04-07:05. Total waiting: T1 10 min, T2 2 min; neither waited for the hopper."""
    raw = copy.deepcopy(SITE)
    raw["equipment"].append({"id": "WB1", "type": "weighbridge", "name": "Weighbridge", "cap": 1, "time": [2, 2, 2]})
    raw["sequences"] = {"unload": ["weigh_in", "tip"]}
    trucks = load_arrival_script({"trucks": [
        {"id": "T1", "activity": "unload", "arrive": "06:50", "commodity": "YM", "tonnes": 30},
        {"id": "T2", "activity": "unload", "arrive": "07:00", "commodity": "YM", "tonnes": 30}]})
    result = TruckFlowModel(load_site_config(raw), trucks, FixedServiceTimes({"tip": 1, "weigh_in": 2}),
                            policy="feasible_first").run()
    m = {t: (x.total_waiting_min, x.hopper_wait_min) for t, x in result.truck_metrics.items()}
    assert m == {"T1": (10, 0), "T2": (2, 0)}


def test_waits_per_commodity_and_overtakes_are_summarised():
    f = run().fairness["unload"]
    ym, wm = f.by_commodity["YM"], f.by_commodity["WM"]
    assert (ym.trucks, ym.mean_total_wait_min, ym.max_total_wait_min) == (2, 0.5, 1)
    assert (wm.trucks, wm.mean_total_wait_min, wm.max_total_wait_min) == (1, 19, 19)
    assert (ym.mean_hopper_wait_min, wm.mean_hopper_wait_min) == (0.5, 19)
    assert wm.mean_turnaround_min == 20  # 07:00 to 07:20
    assert (f.max_overtaken, f.most_overtaken_truck) == (1, "W1")


def test_trucks_still_on_site_count_with_their_waiting_so_far():
    """Stopped at 07:10: W1 is unfinished and has waited 10 min so far."""
    result = run(until=hm("07:10"))
    assert (result.truck_metrics["W1"].total_waiting_min, result.truck_metrics["W1"].unfinished) == (10, True)
    wm = result.fairness["unload"].by_commodity["WM"]
    assert (wm.still_waiting, wm.max_total_wait_min, wm.max_hopper_wait_min) == (1, 10, 10)


def test_starvation_threshold_is_configurable():
    assert run(fairness={"starvation_wait_minutes": 15}).fairness["unload"].starved == 1  # W1 waited 19 min
    assert run(fairness={"starvation_wait_minutes": 30}).fairness["unload"].starved == 0
    by_overtakes = run(fairness={"starvation_wait_minutes": 999, "starvation_overtakes": 1})
    assert by_overtakes.fairness["unload"].starved == 1
    assert [t for t, x in by_overtakes.truck_metrics.items() if x.starved] == ["W1"]


def test_default_threshold_is_listed_as_an_assumption():
    result = run()
    assert "A truck counts as starved after waiting 120 min in total (default reporting threshold)." in result.assumptions


def test_fairness_figures_reach_experiment_results():
    k = kpis_of(run(fairness={"starvation_wait_minutes": 15}))
    assert (k["unload.starved"], k["unload.max_overtaken"]) == (1, 1)
    assert (k["unload.WM.mean_total_wait_min"], k["unload.YM.max_hopper_wait_min"]) == (19, 1)
    golden = {c["name"]: c for c in json.loads((Path(__file__).parent / "golden" / "validation_cases.json").read_text(encoding="utf-8"))["cases"]}
    raw = copy.deepcopy(golden["site_a_valid"]["config"])
    raw["demand"]["load"]["daily"] = 0
    exp = run_experiment(load_site_config(raw), replications=2, base_seed=3)
    assert exp.summary["unload.starved"].n == 2
    assert exp.summary["unload.max_overtaken"].n == 2
    assert exp.summary["unload.YM.mean_total_wait_min"].n == 2
