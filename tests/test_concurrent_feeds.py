"""Concurrent feeds on shared conveyors/elevators (R1 max_concurrent_feeds > 1, A1 merge rule, A2 equal sharing).

Rates: hoppers 400 t/h, conveyor C1 300 t/h, elevator E1 200 t/h. A stream's rate is the slowest of its pit and
each segment's rate divided by the number of streams flowing on that segment.
- One stream alone: min(400, 300, 200) = 200 t/h.
- Two streams sharing C1 and E1: min(400, 150, 100) = 100 t/h each.
"""
from silo_engine.config import load_site_config
from silo_engine.domain.storage import GradedCommodity, MixingRules, StorageBin
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.ledger import ReservationLedger, SegmentClaim
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import TruckFlowModel

YM = GradedCommodity("YM", "*")


def t(tonnes):
    return round(tonnes * 1000)


def site(hoppers, bins, feeds=2, changeovers=None, sequences=None):
    """hoppers: list of (id, level t, commodity, capacity t); all feed C1 -> E1 -> every bin."""
    eq = [{"id": hid, "type": "hopper", "name": hid, "capT": cap, "rate": 400, "tip": [1, 1, 1],
           "commodities": [c], **({"level0": level, "levelCommodity": c} if level else {})}
          for hid, level, c, cap in hoppers]
    eq += [{"id": "C1", "type": "conveyor", "name": "C1", "rate": 300, "max_concurrent_feeds": feeds},
           {"id": "E1", "type": "elevator", "name": "E1", "rate": 200, "max_concurrent_feeds": feeds}]
    eq += [{"id": bid, "type": "bin", "name": bid, "capT": 1000, "commodities": [c],
            **({"inv": inv, "invCommodity": c} if inv else {})} for bid, c, inv in bins]
    edges = [[h[0], "C1"] for h in hoppers] + [["C1", "E1"]] + [["E1", b[0]] for b in bins]
    raw = {"id": "t", "name": "Test silo", "version": 1, "hours": {"open": 7, "close": 18},
           "commodities": [{"id": "YM", "name": "Yellow maize"}, {"id": "WM", "name": "White maize"}],
           "equipment": eq, "edges": edges, "sequences": sequences or {}, "demand": {}}
    if changeovers is not None:
        raw["changeovers"] = changeovers
    return load_site_config(raw)


TIMES = FixedServiceTimes({"tip": 1})


def run(model, until=None):
    result = model.run(until)
    assert result.material_balance_kg == 0 and result.violations == []
    return result


def timeline(result):
    return [(x.pit, x.bin, x.kg, x.flow_started, x.finished) for x in result.transfers]


def test_two_streams_share_capacity_equally():
    """T1.3: H1 and H2 each 30 t maize into B1; both flow at 100 t/h from 07:00: 30 t / 100 t/h = 18 min."""
    s = site([("H1", 30, "YM", 60), ("H2", 30, "YM", 60)], [("B1", "YM", 0)])
    result = run(TruckFlowModel(s, [], TIMES, policy="feasible_first"))
    assert timeline(result) == [("H1", "B1", t(30), hm("07:00"), hm("07:18")),
                                ("H2", "B1", t(30), hm("07:00"), hm("07:18"))]


def test_remaining_stream_speeds_up_when_the_other_finishes():
    """T1.6: H1 has 15 t, H2 30 t. Both at 100 t/h: H1 done at 07:09; H2 has moved 15 t and has 15 t left,
    now alone at 200 t/h: 4.5 min -> 07:13:30."""
    s = site([("H1", 15, "YM", 60), ("H2", 30, "YM", 60)], [("B1", "YM", 0)])
    result = run(TruckFlowModel(s, [], TIMES, policy="feasible_first"))
    assert timeline(result) == [("H1", "B1", t(15), hm("07:00"), hm("07:09")),
                                ("H2", "B1", t(30), hm("07:00"), hm("07:13:30"))]


def test_feed_limit_makes_a_third_stream_wait():
    """Limit 2: H1 and H2 flow at 100 t/h 07:00-07:18; H3 waits, then flows alone at 200 t/h 07:18-07:27."""
    s = site([("H1", 30, "YM", 60), ("H2", 30, "YM", 60), ("H3", 30, "YM", 60)], [("B1", "YM", 0)])
    model = TruckFlowModel(s, [], TIMES, policy="feasible_first")
    run(model, until=hm("07:05"))
    [rid] = [r for r in model.waiting_reasons() if r.startswith("H3/")]
    assert {r.code for r in model.waiting_reasons()[rid]} == {"EQUIPMENT_BUSY"}
    result = run(model)
    assert timeline(result)[2] == ("H3", "B1", t(30), hm("07:18"), hm("07:27"))


def test_different_commodity_cannot_join_a_shared_segment():
    """T1.4: H1 yellow maize, H2 white maize, limit 2. White waits (commodity lock) until 07:09, then flows alone:
    07:09-07:18 (changeover default 0 minutes, stated explicitly)."""
    s = site([("H1", 30, "YM", 60), ("H2", 30, "WM", 60)], [("B1", "YM", 0), ("B2", "WM", 0)],
             changeovers={"default_minutes": 0})
    model = TruckFlowModel(s, [], TIMES, policy="feasible_first")
    run(model, until=hm("07:05"))
    [rid] = [r for r in model.waiting_reasons() if r.startswith("H2/")]
    assert {r.code for r in model.waiting_reasons()[rid]} == {"COMMODITY_LOCK"}
    result = run(model)
    assert timeline(result) == [("H1", "B1", t(30), hm("07:00"), hm("07:09")),
                                ("H2", "B2", t(30), hm("07:09"), hm("07:18"))]


def test_streams_may_only_merge_when_they_go_to_the_same_bin():
    """T1.5 (A1). B1 holds 990 t (10 t free); B2 empty. Both pits hold 30 t maize.
    07:00 H1 sends 10 t to B1 alone (200 t/h, 3 min). H2 cannot use B1 (full once reserved) and cannot merge
    towards B2 while H1 heads for B1: it waits (MERGE_PATH_DIFFERS).
    07:03 H1's part-lot is in. H2 (waiting longer) takes C1 -> E1 -> B2; H1's remaining 20 t join it to B2.
    Both at 100 t/h: H1's 20 t take 12 min -> 07:15. H2 has 10 t left, alone at 200 t/h: 3 min -> 07:18.
    Final: B1 1000 t, B2 50 t."""
    s = site([("H1", 30, "YM", 60), ("H2", 30, "YM", 60)], [("B1", "YM", 990), ("B2", "YM", 0)])
    model = TruckFlowModel(s, [], TIMES, policy="feasible_first")
    run(model, until=hm("07:01"))
    [rid] = [r for r in model.waiting_reasons() if r.startswith("H2/")]
    assert "MERGE_PATH_DIFFERS" in {r.code for r in model.waiting_reasons()[rid]}
    result = run(model)
    assert timeline(result) == [("H1", "B1", t(10), hm("07:00"), hm("07:03")),
                                ("H2", "B2", t(30), hm("07:03"), hm("07:18")),
                                ("H1", "B2", t(20), hm("07:03"), hm("07:15"))]
    assert result.bins == {"B1": (t(1000), ("YM", "*")), "B2": (t(50), ("YM", "*"))}


def test_pit_space_follows_changing_drain_rates():
    """H1 (60 t) holds 40 t and drains at 100 t/h while sharing with H2 (20 t pit, 15 t, also 100 t/h).
    A 40 t truck needs 20 t drained from H1. At 100 t/h that would be 07:12, but H2 finishes at 07:09
    (15 t at 100 t/h); H1 has then drained 15 t and speeds up to 200 t/h: the last 5 t take 1.5 min.
    The truck tips at 07:10:30. (H2 is too small for the truck.)"""
    s = site([("H1", 40, "YM", 60), ("H2", 15, "YM", 20)], [("B1", "YM", 0)], sequences={"unload": ["tip"]})
    trucks = load_arrival_script({"trucks": [
        {"id": "T1", "activity": "unload", "arrive": "07:00", "commodity": "YM", "tonnes": 40}]})
    result = run(TruckFlowModel(s, trucks, TIMES, policy="feasible_first"))
    tip = next(st for st in result.records[0].steps if st.step == "tip")
    assert (tip.unit, tip.started) == ("H1", hm("07:10:30"))


CHANGEOVER_SITE_HOPPERS = [("H3", 10, "WM", 60), ("H1", 30, "YM", 60)]
CHANGEOVER_RULES = {"rules": [{"from": "WM", "to": "YM", "minutes": 5}, {"from": "YM", "to": "WM", "minutes": 5}]}


def test_a_stream_joining_during_a_changeover_waits_for_it_to_finish():
    """H3 (10 t white maize) runs first, 07:00-07:03. H1 and H2 (30 t yellow each) wait for the commodity lock.
    07:03: H1 reserves C1/E1 and changes over white -> yellow (5 min): flows from 07:08.
    H2 joins at 07:03 with no changeover of its own, but the shared equipment is still being cleaned: it may only
    flow from 07:08. Both at 100 t/h from 07:08: 18 min -> 07:26."""
    s = site(CHANGEOVER_SITE_HOPPERS + [("H2", 30, "YM", 60)], [("B1", "YM", 0), ("B2", "WM", 0)],
             changeovers=CHANGEOVER_RULES)
    result = run(TruckFlowModel(s, [], TIMES, policy="feasible_first"))
    assert timeline(result) == [("H3", "B2", t(10), hm("07:00"), hm("07:03")),
                                ("H1", "B1", t(30), hm("07:08"), hm("07:26")),
                                ("H2", "B1", t(30), hm("07:08"), hm("07:26"))]
    assert result.transfers[2].changeover_segments == {}


def test_a_stream_joining_after_the_changeover_needs_none():
    """As above, but H2 starts empty; truck T2 (30 t yellow) arrives 07:10 and tips into H2 07:10-07:11.
    (H1's pit is only 30 t here, so it has no room for T2; otherwise T2 would prefer H1, which holds yellow maize.)
    H1 flows alone at 200 t/h from 07:08: by 07:11 it has moved 10 t (20 t left).
    H2's lot joins at 07:11 with no changeover (the equipment already carries yellow maize).
    Both at 100 t/h: H1's 20 t take 12 min -> 07:23. H2 has then moved 20 t; its last 10 t alone at 200 t/h take
    3 min -> 07:26."""
    s = site([("H3", 10, "WM", 60), ("H1", 30, "YM", 30), ("H2", 0, "YM", 60)], [("B1", "YM", 0), ("B2", "WM", 0)],
             changeovers=CHANGEOVER_RULES, sequences={"unload": ["tip"]})
    trucks = load_arrival_script({"trucks": [
        {"id": "T2", "activity": "unload", "arrive": "07:10", "commodity": "YM", "tonnes": 30}]})
    result = run(TruckFlowModel(s, trucks, TIMES, policy="feasible_first"))
    assert timeline(result) == [("H3", "B2", t(10), hm("07:00"), hm("07:03")),
                                ("H1", "B1", t(30), hm("07:08"), hm("07:23")),
                                ("H2", "B1", t(30), hm("07:11"), hm("07:26"))]
    assert next(st for st in result.records[0].steps if st.step == "tip").unit == "H2"
    assert result.transfers[2].changeover_segments == {}


def test_ledger_refuses_a_merge_with_a_different_remaining_path():
    b = StorageBin("B1", capacity_kg=t(1000), accepts=frozenset({YM}), mixing=MixingRules([]))
    ledger = ReservationLedger(lanes=set(), segments={"E1": 2}, pits={}, bins={"B1": b})
    assert ledger.try_reserve("X1", [SegmentClaim("E1", YM, ("E1", "B1"))], 0) == []
    assert [r.code for r in ledger.try_reserve("X2", [SegmentClaim("E1", YM, ("E1", "B2"))], 0)] == ["MERGE_PATH_DIFFERS"]
    assert ledger.try_reserve("X3", [SegmentClaim("E1", YM, ("E1", "B1"))], 0) == []
