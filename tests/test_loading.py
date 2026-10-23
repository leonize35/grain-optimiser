"""Loading trucks: stock reservation, load-out route, shared equipment with intake (build step: loading).

Site: bin B1 holds yellow maize; intake H1 -> C1 -> E1 -> B1; load-out B1 -> R1 (reclaim, 300 t/h) -> E1 ->
L1 (load point, 250 t/h, setup 5 min). E1 (200 t/h) is shared by intake and loading, exclusive.
A load runs at min(250, 300, 200) = 200 t/h, after the setup: 30 t takes 5 + 9 = 14 min.
"""
import copy

from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import TruckFlowModel

BASE = {
    "id": "l", "name": "Loading silo", "version": 1, "hours": {"open": 7, "close": 18},
    "commodities": [{"id": "YM", "name": "Yellow maize"}],
    "equipment": [
        {"id": "WB1", "type": "weighbridge", "name": "Weighbridge", "cap": 1, "time": [2, 2, 2]},
        {"id": "H1", "type": "hopper", "name": "Hopper 1", "capT": 60, "rate": 400, "tip": [1, 1, 1], "commodities": ["YM"]},
        {"id": "C1", "type": "conveyor", "name": "C1", "rate": 300},
        {"id": "E1", "type": "elevator", "name": "E1", "rate": 200},
        {"id": "B1", "type": "bin", "name": "Bin 1", "capT": 1000, "commodities": ["YM"], "inv": 100, "invCommodity": "YM"},
        {"id": "R1", "type": "conveyor", "name": "Reclaim", "rate": 300},
        {"id": "L1", "type": "loadpoint", "name": "Load-out", "rate": 250, "setup": [5, 5, 5]},
    ],
    "edges": [["H1", "C1"], ["C1", "E1"], ["E1", "B1"], ["B1", "R1"], ["R1", "E1"], ["E1", "L1"]],
    "sequences": {"unload": ["tip"], "load": ["load"]}, "demand": {},
}
TIMES = FixedServiceTimes({"tip": 1, "load": 5, "weigh_in": 2, "weigh_out": 2})


def raw(**changes):
    r = copy.deepcopy(BASE)
    r.update(changes)
    return r


def trucks(*rows):
    out = []
    for tid, act, at, tonnes, extra in rows:
        out.append({"id": tid, "activity": act, "arrive": at, "commodity": "YM", "tonnes": tonnes, **extra})
    return load_arrival_script({"trucks": out})


def run(r, script, until=None):
    model = TruckFlowModel(load_site_config(r), script, TIMES, policy="feasible_first")
    result = model.run(until)
    assert result.material_balance_kg == 0 and result.violations == []
    return model, result


def load_of(result, tid):
    return next(x for x in result.loads if x.truck_id == tid)


def test_load_takes_setup_plus_flow_and_removes_stock():
    """Loading truck (34 t): weigh-in 07:00-07:02; load 07:02 + 5 min setup + 34 t / 200 t/h (10.2 min) = 07:17:12;
    weigh-out 07:17:12-07:19:12. Bin 1: 100 t - 34 t = 66 t."""
    r = raw(sequences={"unload": ["tip"], "load": ["weigh_in", "load", "weigh_out"]})
    _, result = run(r, trucks(("L01", "load", "07:00", 34, {})))
    x = load_of(result, "L01")
    assert (x.bin, x.kg, x.started, x.flow_started, x.finished) == ("B1", 34_000, hm("07:02"), hm("07:07"), hm("07:17:12"))
    assert result.records[0].departed == hm("07:19:12")
    assert result.bins["B1"][0] == 66_000
    assert result.dispatched_kg == 34_000


def test_loading_waits_for_stock_that_intake_brings():
    """Bin 1 holds 10 t; a 30 t loading truck arrives 07:00 and waits (stock short). An unloading truck tips 30 t
    07:00-07:01; its lot flows into Bin 1 07:01-07:10 (40 t). The load then runs 07:10-07:24 (5 + 9 min)."""
    r = raw()
    next(e for e in r["equipment"] if e["id"] == "B1")["inv"] = 10
    model, _ = run(r, trucks(("L01", "load", "07:00", 30, {}), ("U01", "unload", "07:00", 30, {})), until=hm("07:05"))
    # Both are true at 07:05: the bin is short, and E1 is busy carrying the intake lot.
    assert sorted(w.code for w in model.waiting_reasons()["L01/load"]) == ["EQUIPMENT_BUSY", "STOCK_SHORT"]
    result = model.run()
    x = load_of(result, "L01")
    assert (x.started, x.finished) == (hm("07:10"), hm("07:24"))
    assert result.stall is None


def test_intake_and_loading_share_the_elevator():
    """The load (30 t) starts 07:00 and holds E1 until 07:14. The unloading truck's lot (tipped 07:00-07:01) waits
    for E1, then flows 07:14-07:23."""
    _, result = run(raw(), trucks(("L01", "load", "07:00", 30, {}), ("U01", "unload", "07:00", 30, {})))
    assert (load_of(result, "L01").started, load_of(result, "L01").finished) == (hm("07:00"), hm("07:14"))
    t = result.transfers[0]
    assert (t.flow_started, t.finished) == (hm("07:14"), hm("07:23"))


def test_loading_takes_the_ordered_grade_only():
    """Bin 1 holds grade 1, Bin 2 grade 2 (both reachable). A truck ordering grade 2 loads from Bin 2."""
    r = raw(commodities=[{"id": "YM", "name": "Yellow maize", "grades": ["1", "2"]}])
    b1 = next(e for e in r["equipment"] if e["id"] == "B1")
    b1.update(accepts=[{"commodity": "YM", "grades": ["1"]}], invGrade="1")
    r["equipment"].append({"id": "B2", "type": "bin", "name": "Bin 2", "capT": 1000, "commodities": ["YM"],
                           "accepts": [{"commodity": "YM", "grades": ["2"]}], "inv": 100, "invCommodity": "YM", "invGrade": "2"})
    r["edges"] += [["E1", "B2"], ["B2", "R1"]]
    r["sequences"] = {"load": ["load"]}
    _, result = run(r, trucks(("L01", "load", "07:00", 30, {"grade": "2"})))
    assert load_of(result, "L01").bin == "B2"
    assert result.bins["B1"][0] == 100_000 and result.bins["B2"][0] == 70_000


def test_waiting_for_stock_that_can_never_come_is_a_stall():
    """Bin 1 holds 10 t and no unloading truck is coming: nothing can ever supply the load."""
    r = raw()
    next(e for e in r["equipment"] if e["id"] == "B1")["inv"] = 10
    model = TruckFlowModel(load_site_config(r), trucks(("L01", "load", "07:00", 30, {})), TIMES, policy="feasible_first")
    result = model.run()
    assert result.stall is not None and result.stall.time == hm("07:00")
    assert [w.code for w in result.stall.waiting["L01/load"]] == ["STOCK_SHORT"]


def test_generated_day_with_loading_runs_clean_on_prototype_site_a():
    import json
    from pathlib import Path
    from silo_engine.inputs.generated import generate_arrivals
    from silo_engine.sim.service_times import StochasticServiceTimes
    golden = {c["name"]: c for c in json.loads((Path(__file__).parent / "golden" / "validation_cases.json").read_text(encoding="utf-8"))["cases"]}
    site = load_site_config(golden["site_a_valid"]["config"])  # loading demand 8 trucks/day, opening stock 3100 t
    result = TruckFlowModel(site, generate_arrivals(site, 5), StochasticServiceTimes(site, 5), policy="feasible_first").run()
    assert result.stall is None and result.violations == [] and result.material_balance_kg == 0
    assert result.summary["load"].completed > 0 and result.dispatched_kg > 0
