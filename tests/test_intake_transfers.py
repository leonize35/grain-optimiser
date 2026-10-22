"""Hopper pits and intake transfers on exclusive segments (build step 2; rules R1 default, R2, R7).

Route rate = slowest of the hopper discharge rate and the conveyor/elevator rates on the route.
In these sites hoppers discharge at 400 t/h, conveyors 300 t/h and elevators 200 t/h, so every route runs at
200 t/h: 30 t takes 9 min, 40 t 12 min, 10 t 3 min, 20 t 6 min.
Every scenario also asserts zero material-balance error and no invariant violations after any event.
"""
import pytest

from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel


def t(tonnes):
    return round(tonnes * 1000)


def hopper(hid, commodities=("YM",), level=0, level_commodity="YM", admission="full_load_space"):
    h = {"id": hid, "type": "hopper", "name": hid, "capT": 60, "rate": 400, "tip": [1, 1, 1],
         "commodities": list(commodities), "tip_admission": admission}
    if level:
        h.update(level0=level, levelCommodity=level_commodity)
    return h


def conveyor(cid, rate=300):
    return {"id": cid, "type": "conveyor", "name": cid, "rate": rate}


def elevator(eid, rate=200):
    return {"id": eid, "type": "elevator", "name": eid, "rate": rate}


def storage(bid, commodities=("YM",), cap=1000, inv=0, inv_commodity=None):
    b = {"id": bid, "type": "bin", "name": bid, "capT": cap, "commodities": list(commodities)}
    if inv:
        b.update(inv=inv, invCommodity=inv_commodity)
    return b


WB = {"id": "WB1", "type": "weighbridge", "name": "WB1", "cap": 1, "time": [2, 2, 2]}


def site(equipment, edges, sequences=None, open_hour=7, changeovers=None):
    raw = {
        "id": "t", "name": "Test silo", "version": 1, "hours": {"open": open_hour, "close": 18},
        "commodities": [{"id": "YM", "name": "Yellow maize"}, {"id": "WM", "name": "White maize"},
                        {"id": "SB", "name": "Soybeans"}],
        "equipment": equipment, "edges": edges, "sequences": sequences or {}, "demand": {}}
    if changeovers is not None:
        raw["changeovers"] = changeovers
    return load_site_config(raw)


def trucks(*rows):
    return load_arrival_script({"trucks": [
        {"id": tid, "activity": "unload", "arrive": arrive, "commodity": c, "tonnes": tonnes}
        for tid, arrive, c, tonnes in rows]})


TIMES = FixedServiceTimes({"weigh_in": 2, "weigh_out": 2, "tip": 1})


def run(model, until=None):
    result = model.run(until)
    assert result.material_balance_kg == 0
    assert result.violations == []
    return result


def transfers(result):
    return [(x.pit, x.bin, x.kg, x.started, x.finished) for x in result.transfers]


def test_independent_routes_carry_different_commodities_at_the_same_time():
    """T1.1: H1 (30 t maize) -> C1 -> E1 -> B1 and H3 (30 t soybeans) -> C2 -> E2 -> B4 share nothing.
    Both start at opening, 07:00, and finish at 07:09."""
    s = site([hopper("H1", level=30), hopper("H3", ("SB",), level=30, level_commodity="SB"),
              conveyor("C1"), elevator("E1"), conveyor("C2"), elevator("E2"),
              storage("B1"), storage("B4", ("SB",))],
             [["H1", "C1"], ["C1", "E1"], ["E1", "B1"], ["H3", "C2"], ["C2", "E2"], ["E2", "B4"]])
    result = run(TruckFlowModel(s, [], TIMES, policy="feasible_first"))
    assert transfers(result) == [("H1", "B1", t(30), hm("07:00"), hm("07:09")),
                                 ("H3", "B4", t(30), hm("07:00"), hm("07:09"))]
    assert result.bins == {"B1": (t(30), ("YM", "*")), "B4": (t(30), ("SB", "*"))}


SHARED = site([hopper("H1", level=30), hopper("H2", level=30), conveyor("C1"), elevator("E1"), storage("B1")],
              [["H1", "C1"], ["H2", "C1"], ["C1", "E1"], ["E1", "B1"]])


def test_exclusive_shared_elevator_serves_one_lot_at_a_time():
    """T1.2: H1 and H2 both feed C1 -> E1 (exclusive). H1's lot 07:00-07:09; H2 waits, then 07:09-07:18."""
    result = run(TruckFlowModel(SHARED, [], TIMES, policy="feasible_first"))
    assert transfers(result) == [("H1", "B1", t(30), hm("07:00"), hm("07:09")),
                                 ("H2", "B1", t(30), hm("07:09"), hm("07:18"))]


def test_waiting_transfer_explains_which_equipment_is_busy():
    model = TruckFlowModel(SHARED, [], TIMES, policy="feasible_first")
    run(model, until=hm("07:05"))
    reasons = model.waiting_reasons()
    [rid] = [r for r in reasons if r.startswith("H2/intake")]
    assert {(r.code, r.resource) for r in reasons[rid]} == {("EQUIPMENT_BUSY", "C1"), ("EQUIPMENT_BUSY", "E1")}


LINE = [hopper("H1"), conveyor("C1"), elevator("E1"), storage("B1", inv=100, inv_commodity="YM"), WB]
LINE_EDGES = [["H1", "C1"], ["C1", "E1"], ["E1", "B1"]]


def test_truck_leaves_before_its_grain_reaches_the_bin():
    """T2.1: weigh-in 07:00-07:02, tip 07:02-07:03 (lot created 07:03), weigh-out 07:03-07:05, departs 07:05.
    The lot's transfer runs 07:03-07:12, after the truck has gone. Bin: 100 t + 30 t = 130 t."""
    s = site(LINE, LINE_EDGES, {"unload": ["weigh_in", "tip", "weigh_out"]})
    result = run(TruckFlowModel(s, trucks(("T1", "07:00", "YM", 30)), TIMES, policy="feasible_first"))
    rec = result.records[0]
    assert rec.departed == hm("07:05")
    assert transfers(result) == [("H1", "B1", t(30), hm("07:03"), hm("07:12"))]
    assert result.transfers[0].truck_id == "T1"
    assert result.bins["B1"] == (t(130), ("YM", "*"))


def pit_site(admission, commodities=("YM",)):
    # Two commodities can share C1/E1 here, so changeover rules are required (R3); these pit tests are not about
    # changeovers, so an explicit zero default is configured.
    return site([hopper("H1", commodities, level=40, admission=admission), conveyor("C1"), elevator("E1"),
                 storage("B1", ("YM", "WM"))], LINE_EDGES, {"unload": ["tip"]}, changeovers={"default_minutes": 0})


def tip_start(result, truck_id):
    rec = next(r for r in result.records if r.truck_id == truck_id)
    return next(s for s in rec.steps if s.step == "tip").started


def test_full_load_space_waits_until_enough_grain_has_drained():
    """T2.2: 60 t pit holds 40 t, draining at 200 t/h from 07:00 (40 t -> 07:12). A 30 t truck at 07:00 needs
    10 t to drain = 3 min: it tips at 07:03 (until 07:04). Its lot follows the opening lot: 07:12-07:21."""
    result = run(TruckFlowModel(pit_site("full_load_space"), trucks(("T1", "07:00", "YM", 30)), TIMES,
                                policy="feasible_first"))
    assert tip_start(result, "T1") == hm("07:03")
    assert transfers(result) == [("H1", "B1", t(40), hm("07:00"), hm("07:12")),
                                 ("H1", "B1", t(30), hm("07:12"), hm("07:21"))]


def test_empty_pit_rule_waits_until_the_pit_is_empty():
    """T2.3: same pit, rule empty_pit: the truck tips when the 40 t have gone, at 07:12."""
    result = run(TruckFlowModel(pit_site("empty_pit"), trucks(("T1", "07:00", "YM", 30)), TIMES,
                                policy="feasible_first"))
    assert tip_start(result, "T1") == hm("07:12")


def test_other_commodity_waits_for_an_empty_pit():
    """T2.4 (A4): pit holds 40 t yellow maize; a white maize truck has space from 07:03 but must wait until the
    pit is empty at 07:12. (Run stops at 07:12:30, before its lot would need a commodity changeover.)"""
    model = TruckFlowModel(pit_site("full_load_space", ("YM", "WM")), trucks(("T1", "07:00", "WM", 30)), TIMES,
                           policy="feasible_first")
    run(model, until=hm("07:05"))
    assert [r.code for r in model.waiting_reasons()["T1/tip"]] == ["PIT_INCOMPATIBLE"]
    result = run(model, until=hm("07:12:30"))
    assert tip_start(result, "T1") == hm("07:12")


def test_lot_is_split_when_the_preferred_bin_fills():
    """Pit holds 30 t maize. B1 (already maize, 980/1000 t) is preferred; it takes 20 t (07:00-07:06).
    The remaining 10 t go to empty B2 (07:06-07:09)."""
    s = site([hopper("H1", level=30), conveyor("C1"), elevator("E1"),
              storage("B1", inv=980, inv_commodity="YM"), storage("B2")],
             [["H1", "C1"], ["C1", "E1"], ["E1", "B1"], ["E1", "B2"]])
    result = run(TruckFlowModel(s, [], TIMES, policy="feasible_first"))
    assert transfers(result) == [("H1", "B1", t(20), hm("07:00"), hm("07:06")),
                                 ("H1", "B2", t(10), hm("07:06"), hm("07:09"))]
    assert result.bins == {"B1": (t(1000), ("YM", "*")), "B2": (t(10), ("YM", "*"))}
    assert result.pits == {"H1": 0}


def test_truck_without_a_hopper_route_for_its_commodity_is_a_model_error():
    s = site([hopper("H1"), conveyor("C1"), elevator("E1"), storage("B1")], LINE_EDGES, {"unload": ["tip"]})
    with pytest.raises(ModelError, match="Soybeans|SB"):
        TruckFlowModel(s, trucks(("T1", "07:00", "SB", 30)), TIMES, policy="feasible_first")
