"""Grain transfer order: oldest grain first across pits (the prototype's 'fifo' transfer rule, "Oldest grain first").

Found by the differential check against the prototype (docs/PORT_LOG.md step 11): ordering pit transfers by when
the request was filed made the elevator rotate between pits, causing far more changeovers than the prototype.

Site: H1 (yellow maize only) -> C1, H2 (white maize only) -> C2; both feed elevator E1 (200 t/h, exclusive) ->
B1 (yellow) / B2 (white). Changeovers: yellow -> white 8 min, white -> yellow 5 min. Tipping 1 min; 30 t lots
flow 9 min.
  T1 (yellow) 07:00 tips into H1 07:00-07:01: lot L1 created 07:01, flows 07:01-07:10.
  T2 (yellow) 07:00 tips into H1 after T1, 07:01-07:02: lot L2 created 07:02, waits for E1.
  T3 (white)  07:04 tips into H2 07:04-07:05: lot created 07:05, waits for E1.
  07:10: L2 (07:02) is older than T3's lot (07:05), so L2 goes next: 07:10-07:19, no changeover.
  07:19: T3's lot: changeover yellow -> white 8 min, flows 07:27-07:36.
"""
from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import TruckFlowModel

SITE = {
    "id": "o", "name": "Order silo", "version": 1, "hours": {"open": 7, "close": 18},
    "commodities": [{"id": "YM", "name": "Yellow maize"}, {"id": "WM", "name": "White maize"}],
    "equipment": [
        {"id": "H1", "type": "hopper", "name": "Hopper 1", "capT": 60, "rate": 400, "tip": [1, 1, 1], "commodities": ["YM"]},
        {"id": "H2", "type": "hopper", "name": "Hopper 2", "capT": 60, "rate": 400, "tip": [1, 1, 1], "commodities": ["WM"]},
        {"id": "C1", "type": "conveyor", "name": "C1", "rate": 300},
        {"id": "C2", "type": "conveyor", "name": "C2", "rate": 300},
        {"id": "E1", "type": "elevator", "name": "E1", "rate": 200},
        {"id": "B1", "type": "bin", "name": "B1", "capT": 1000, "commodities": ["YM"]},
        {"id": "B2", "type": "bin", "name": "B2", "capT": 1000, "commodities": ["WM"]},
    ],
    "edges": [["H1", "C1"], ["H2", "C2"], ["C1", "E1"], ["C2", "E1"], ["E1", "B1"], ["E1", "B2"]],
    "sequences": {"unload": ["tip"]}, "demand": {},
    "changeovers": {"rules": [{"from": "YM", "to": "WM", "minutes": 8}, {"from": "WM", "to": "YM", "minutes": 5}]},
}
TRUCKS = [("T1", "07:00", "YM"), ("T2", "07:00", "YM"), ("T3", "07:04", "WM")]


def test_oldest_grain_goes_first_across_pits():
    trucks = load_arrival_script({"trucks": [
        {"id": tid, "activity": "unload", "arrive": at, "commodity": c, "tonnes": 30} for tid, at, c in TRUCKS]})
    result = TruckFlowModel(load_site_config(SITE), trucks, FixedServiceTimes({"tip": 1}), policy="feasible_first").run()
    assert result.material_balance_kg == 0 and result.violations == []
    assert [(x.truck_id, x.flow_started, x.finished) for x in result.transfers] == [
        ("T1", hm("07:01"), hm("07:10")), ("T2", hm("07:10"), hm("07:19")), ("T3", hm("07:27"), hm("07:36"))]
    assert sum(1 for x in result.transfers if x.changeover_segments) == 1
