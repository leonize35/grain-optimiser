"""Planned grain moves between bins: turning, transfers and freeing a bin (rules confirmed by the user 2026-11-07).
Hand-traced. Test inputs only.

- `grain_moves`: [{id, day, at "HH:MM", from_bin, to_bin, tonnes (None: all the stock when it starts)}]. A move
  waits for a free route (bin -> conveyors/elevators -> bin, without a cleaner or dryer) and gives way to truck
  intake: it does not start while grain in a pit waits for a route sharing equipment with it, and intake is tried
  first at the same moment. It runs at the slowest equipment rate on the route; changeover and clear times apply.
- Reserved as one transaction: the route, the stock in the source bin and the space in the destination. If less
  stock or space is available than asked, the possible part moves and the move is recorded as short, with why.
- Turning (from_bin == to_bin): the grain goes out and back; the stock is held for the move, the bin's contents
  are unchanged.
- Moves run at any time of day (they are planned explicitly). Grain is conserved: the flow audit replays them.

Site: hopper H1 (tip 5 min, 1 800 t/h) -> C1 -> E1 (1 800 t/h) -> bins B1 (5 000 t, 1 000 t of YM at the start),
B2 (5 000 t), B3 (100 t); reclaim B1/B2 -> C2 (600 t/h = 10 t/min) -> E1.
"""
import copy

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config
from silo_engine.config.rules_validation import validate_rules
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import TruckFlowModel

RAW = {
    "id": "moves", "name": "Grain moves test site", "version": 1, "hours": {"open": 7, "close": 18},
    "commodities": [{"id": "YM", "name": "Yellow maize"}],
    "equipment": [
        {"id": "H1", "type": "hopper", "name": "H1", "capT": 60, "rate": 1800, "tip": [5, 5, 5], "commodities": ["YM"]},
        {"id": "C1", "type": "conveyor", "name": "C1", "rate": 1800},
        {"id": "E1", "type": "elevator", "name": "E1", "rate": 1800},
        {"id": "C2", "type": "conveyor", "name": "Reclaim", "rate": 600},
        {"id": "B1", "type": "bin", "name": "B1", "capT": 5000, "commodities": ["YM"], "inv": 1000, "invCommodity": "YM"},
        {"id": "B2", "type": "bin", "name": "B2", "capT": 5000, "commodities": ["YM"]},
        {"id": "B3", "type": "bin", "name": "B3", "capT": 100, "commodities": ["YM"]}],
    "edges": [["H1", "C1"], ["C1", "E1"], ["E1", "B1"], ["E1", "B2"], ["E1", "B3"], ["B1", "C2"], ["B2", "C2"],
              ["C2", "E1"]],
    "sequences": {"unload": ["tip"]}, "demand": {}, "changeovers": {"default_minutes": 0}}


def run(moves, trucks=()):
    raw = copy.deepcopy(RAW)
    raw["grain_moves"] = moves
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": at, "commodity": "YM", "tonnes": 30} for t, at in trucks]})
    r = TruckFlowModel(s, script, FixedServiceTimes({"tip": 5}), policy="feasible_first").run()
    audit = audit_flow(s, script, r)
    assert r.violations == [] and r.material_balance_kg == 0 and r.stall is None
    assert audit.ok, audit.problems
    return r


def mv(id, frm, to, tonnes, at="08:00"):
    return {"id": id, "at": at, "from_bin": frm, "to_bin": to, "tonnes": tonnes}


def test_a_planned_move_between_bins():
    """300 t from B1 to B2 at 08:00 over C2 (10 t/min): 08:00-08:30."""
    r = run([mv("M1", "B1", "B2", 300)])
    m = r.moves[0]
    assert (m.path, m.started, m.flow_started, m.finished, m.kg, m.short) == (
        ["B1", "C2", "E1", "B2"], hm("08:00"), hm("08:00"), hm("08:30"), 300000, None)
    assert (r.bins["B1"][0], r.bins["B2"][0]) == (700000, 300000)


def test_moving_everything():
    r = run([mv("M1", "B1", "B2", None)])
    assert (r.moves[0].kg, r.moves[0].finished, r.bins["B1"][0]) == (1000000, hm("09:40"), 0)


def test_turning_a_bin_keeps_its_contents():
    """B1 -> B1, 100 t: the route is busy 08:00-08:10; B1 still holds 1 000 t."""
    r = run([mv("T", "B1", "B1", 100)])
    m = r.moves[0]
    assert (m.path, m.finished, m.kg, r.bins["B1"][0]) == (["B1", "C2", "E1", "B1"], hm("08:10"), 100000, 1000000)


def test_a_move_larger_than_the_space_is_short():
    """B3 holds 100 t: 100 t of the 300 t move (08:00-08:10); recorded short."""
    r = run([mv("M1", "B1", "B3", 300)])
    m = r.moves[0]
    assert (m.kg, m.requested_kg, m.finished) == (100000, 300000, hm("08:10"))
    assert "B3" in m.short and "space" in m.short


def test_a_move_gives_way_to_intake():
    """T1 tips 07:55-08:00; its grain drains over C1 -> E1 08:00-08:01. The move needs E1 too: it starts 08:01."""
    r = run([mv("M1", "B1", "B2", 300)], trucks=[("T1", "07:55")])
    t = r.transfers[0]
    assert (t.started, t.finished) == (hm("08:00"), hm("08:01"))
    assert (r.moves[0].started, r.moves[0].finished) == (hm("08:01"), hm("08:31"))
    causes = {k for cell in r.wait_causes["grain"].values() for k in cell}
    assert any(k.startswith("EQUIPMENT_BUSY:E1") or k.startswith("GIVES_WAY") for k in causes)


def test_without_moves_nothing_changes():
    r = run([])
    assert r.moves == [] and r.bins["B1"][0] == 1000000


@pytest.mark.parametrize("move, words", [
    (mv("M1", "B1", "B9", 10), "unknown bin B9"),
    (mv("M1", "B1", "B2", 10, at="25:00"), "time"),
    (mv("M1", "B3", "B2", 10), "no route"),
])
def test_invalid_moves_are_refused(move, words):
    raw = copy.deepcopy(RAW)
    raw["grain_moves"] = [move]
    msgs = [i.msg for i in validate_rules(load_site_config(raw)).errors]
    assert any(words in m for m in msgs), msgs


def test_move_ids_are_unique():
    raw = copy.deepcopy(RAW)
    raw["grain_moves"] = [mv("M1", "B1", "B2", 10), mv("M1", "B2", "B1", 10)]
    assert any("more than once" in i.msg for i in validate_rules(load_site_config(raw)).errors)
