"""Interrupted transfers (docs/INTERRUPTED_TRANSFERS.md): scheduled equipment outages, the "hold" recovery rule,
resumption of the same transfer, and grain accounting. Every case is checked by the engine's balance and by the
independent flow audit.

Common figures: tipping 1 min; 30 t lots; elevators 200 t/h (30 t in 9 min, 1 t per 18 s); changeovers 0 min.
"""
import copy

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import ConfigSchemaError, load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel
from test_loading import BASE as LOADING_SITE
from test_starvation_diagnostics import ONE_HOPPER, TWO_SHARED


def outage(equipment, start, end=None, day=1):
    o = {"equipment": equipment, "day": day, "start": start}
    if end:
        o["end"] = end
    return o


def run(raw, rows, until=None, days=1, outages=()):
    raw = copy.deepcopy(raw)
    raw["outages"] = list(outages)
    site = load_site_config(raw)
    trucks = load_arrival_script({"trucks": [
        {"id": t, "activity": act, "arrive": at, "commodity": c, "tonnes": kg} for t, act, at, c, kg in rows]})
    model = TruckFlowModel(site, trucks, FixedServiceTimes({"tip": 1, "load": 5}), policy="feasible_first", days=days)
    r = model.run(until)
    audit = audit_flow(site, trucks, r)
    assert r.material_balance_kg == 0 and r.violations == []
    assert audit.ok, audit.problems
    return r, audit, model


def unload(tid, at="07:00", c="YM", kg=30):
    return (tid, "unload", at, c, kg)


def spans(record):
    return [tuple(x) for x in record.interruptions]


# ---- interruption before the transfer starts ----

def test_route_down_before_the_transfer_makes_it_wait_and_the_truck_still_leaves():
    """E1 is down 06:00-07:05. Y1 tips 07:00-07:01 and leaves; its lot waits (EQUIPMENT_DOWN) and flows 07:05-07:14."""
    r, _, model = run(ONE_HOPPER, [unload("Y1")], until=hm("07:03"), outages=[outage("E1", "06:00", "07:05")])
    assert [w.code for w in model.waiting_reasons()["H1/intake#1"]] == ["EQUIPMENT_DOWN"]
    assert r.records[0].departed == hm("07:01")
    r, *_ = run(ONE_HOPPER, [unload("Y1")], outages=[outage("E1", "06:00", "07:05")])
    t = r.transfers[0]
    assert (t.started, t.finished, spans(t)) == (hm("07:05"), hm("07:14"), [])


def test_another_configured_route_is_used_while_equipment_is_down():
    """C1 feeds two elevators to B1. With E1 down, the lot goes via E2 at once (07:01-07:10)."""
    raw = copy.deepcopy(ONE_HOPPER)
    raw["equipment"].append({"id": "E2", "type": "elevator", "name": "E2", "rate": 200})
    raw["edges"] += [["C1", "E2"], ["E2", "B1"]]
    r, *_ = run(raw, [unload("Y1")], outages=[outage("E1", "06:00", "12:00")])
    assert (r.transfers[0].path, r.transfers[0].started, r.transfers[0].finished) == (
        ["H1", "C1", "E2", "B1"], hm("07:01"), hm("07:10"))


# ---- interruption during the transfer, after partial progress ----

def test_stopped_mid_flow_the_grain_is_held_in_transit_then_the_same_transfer_resumes():
    """Y1's lot flows from 07:01. C1 stops 07:04-07:08: 10 t have left the pit (in transit), 20 t remain.
    At 07:06: nothing delivered, 10 t on the route, 20 t at the source; the route stays reserved.
    The same transfer resumes at 07:08 and finishes at 07:14 (20 t in 6 min)."""
    down = [outage("C1", "07:04", "07:08")]
    r, audit, model = run(ONE_HOPPER, [unload("Y1")], until=hm("07:06"), outages=down)
    t, lot = r.transfers[0], r.lots["L-Y1"]
    assert (t.finished, spans(t)) == (None, [(hm("07:04"), None)])
    assert (lot.stored_kg, lot.on_route_kg, lot.in_transit_kg - lot.on_route_kg) == (0, 10_000, 20_000)
    assert (r.bins["B1"][0], r.pits["H1"]) == (0, 30_000)
    assert audit.in_transit == ["transfer H1/intake#1: 30000 kg H1 -> B1"]
    assert model.ledger.holders("C1") == ["H1/intake#1"] and model.ledger.holders("E1") == ["H1/intake#1"]
    r, *_ = run(ONE_HOPPER, [unload("Y1")], outages=down)
    t = r.transfers[0]
    assert (len(r.transfers), t.id, t.finished, t.released, spans(t)) == (
        1, "H1/intake#1", hm("07:14"), hm("07:14"), [(hm("07:04"), hm("07:08"))])
    assert (r.bins["B1"][0], r.lots["L-Y1"].stored_at, r.lots["L-Y1"].on_route_kg) == (30_000, hm("07:14"), 0)


def test_grain_already_delivered_is_kept_when_a_later_part_is_interrupted():
    """B1 holds 20 t: the first 20 t reach B1 at 07:07. The other 10 t flow to B3 from 07:07; E1 stops 07:08-07:12
    with 3333 kg on the route. At 07:10: B1 20 t, B3 0, 6667 kg still in the pit. Resumed: B3 receives 10 t at 07:14."""
    raw = copy.deepcopy(ONE_HOPPER)
    raw["equipment"][3]["capT"] = 20
    raw["equipment"].append({"id": "B3", "type": "bin", "name": "B3", "capT": 1000, "commodities": ["YM"]})
    raw["edges"].append(["E1", "B3"])
    down = [outage("E1", "07:08", "07:12")]
    r, *_ = run(raw, [unload("Y1")], until=hm("07:10"), outages=down)
    lot = r.lots["L-Y1"]
    assert (r.bins["B1"][0], r.bins["B3"][0], r.pits["H1"]) == (20_000, 0, 10_000)
    assert (lot.stored_kg, lot.in_transit_kg, lot.on_route_kg) == (20_000, 10_000, 3_333)
    r, *_ = run(raw, [unload("Y1")], outages=down)
    assert [(x.bin, x.finished, spans(x)) for x in r.transfers] == [
        ("B1", hm("07:07"), []), ("B3", hm("07:14"), [(hm("07:08"), hm("07:12"))])]
    assert (r.bins["B1"][0], r.bins["B3"][0]) == (20_000, 10_000)


def test_changeover_keeps_elapsing_and_flow_waits_for_the_restart():
    """Changeovers 4 min. Y1's lot flows 07:01-07:10 (first use: no changeover). W1 tips into the empty pit
    07:10-07:11; its transfer reserves the route at 07:11 and changes over until 07:15. E1 is down 07:12-07:20,
    so the flow starts at 07:20 (assumption I3) and ends at 07:29."""
    raw = copy.deepcopy(ONE_HOPPER)
    raw["changeovers"] = {"default_minutes": 4}
    r, *_ = run(raw, [unload("Y1"), unload("W1", c="WM")], outages=[outage("E1", "07:12", "07:20")])
    w = r.transfers[1]
    assert (w.started, w.flow_started, w.finished, spans(w)) == (
        hm("07:11"), hm("07:20"), hm("07:29"), [(hm("07:12"), hm("07:20"))])


# ---- shared routes ----

def test_a_held_route_keeps_incompatible_grain_out_until_the_transfer_completes():
    """H1 and H2 share C1/E1. Y1 (H1) flows from 07:01; W1 (H2) waits for the route. E1 stops 07:03-07:20 with 6.67 t
    of Y1's lot in transit: the route stays locked to yellow maize, so W1's lot cannot enter it. Y1 resumes at
    07:20 (23.33 t, 7 min, done 07:27); only then does W1's lot go (07:27-07:36)."""
    r, *_ = run(TWO_SHARED, [unload("Y1"), unload("W1", c="WM")], outages=[outage("E1", "07:03", "07:20")])
    y, w = r.transfers
    assert (y.pit, y.finished, y.released, spans(y)) == ("H1", hm("07:27"), hm("07:27"), [(hm("07:03"), hm("07:20"))])
    assert (w.pit, w.started, w.finished) == ("H2", hm("07:27"), hm("07:36"))


def test_a_stream_on_a_shared_elevator_keeps_its_slot_while_the_other_takes_the_capacity():
    """H1 -> C1 and H2 -> C2 both feed E1 (2 feeds) into B1. Both lots flow from 07:01 at 100 t/h each.
    C2 stops 07:04-07:10 with 5 t of each lot moved. Stream 1 alone runs at 200 t/h: 20 t by 07:10; then both
    at 100 t/h again: stream 1 finishes at 07:13; stream 2 (25 t left at 07:10) has 20 t left at 07:13 and
    finishes alone at 200 t/h at 07:19."""
    raw = copy.deepcopy(ONE_HOPPER)
    raw["commodities"] = raw["commodities"][:1]
    raw["equipment"] = [
        {"id": "H1", "type": "hopper", "name": "H1", "capT": 60, "rate": 400, "tip": [1, 1, 1], "commodities": ["YM"]},
        {"id": "H2", "type": "hopper", "name": "H2", "capT": 60, "rate": 400, "tip": [1, 1, 1], "commodities": ["YM"]},
        {"id": "C1", "type": "conveyor", "name": "C1", "rate": 300}, {"id": "C2", "type": "conveyor", "name": "C2", "rate": 300},
        {"id": "E1", "type": "elevator", "name": "E1", "rate": 200, "max_concurrent_feeds": 2},
        {"id": "B1", "type": "bin", "name": "B1", "capT": 1000, "commodities": ["YM"]}]
    raw["edges"] = [["H1", "C1"], ["H2", "C2"], ["C1", "E1"], ["C2", "E1"], ["E1", "B1"]]
    r, *_ = run(raw, [unload("Y1"), unload("Y2")], outages=[outage("C2", "07:04", "07:10")])
    s1, s2 = sorted(r.transfers, key=lambda x: x.pit)
    assert (s1.finished, spans(s1)) == (hm("07:13"), [])
    assert (s2.finished, spans(s2)) == (hm("07:19"), [(hm("07:04"), hm("07:10"))])


# ---- end of the operating day and of the run ----

def test_transfer_still_suspended_when_the_run_ends_is_accounted_for():
    """C1 stops at 07:04 with no end. Y1 left at 07:01; its transfer stays suspended with 10 t on the route and
    20 t at the source; nothing is lost, nothing is delivered, the route stays reserved."""
    r, audit, model = run(ONE_HOPPER, [unload("Y1")], outages=[outage("C1", "07:04")])
    t, lot = r.transfers[0], r.lots["L-Y1"]
    assert (t.finished, spans(t), r.records[0].departed) == (None, [(hm("07:04"), None)], hm("07:01"))
    assert (lot.stored_kg, lot.on_route_kg, lot.in_transit_kg) == (0, 10_000, 30_000)
    assert (r.bins["B1"][0], r.pits["H1"], r.stall) == (0, 30_000, None)
    assert audit.in_transit == ["transfer H1/intake#1: 30000 kg H1 -> B1"]


@pytest.mark.parametrize("days, finished", [(1, None), (2, hm("07:06") + 24 * 60 * 60_000)])
def test_restart_after_close_waits_for_the_next_opening_when_transfers_stop_at_close(days, finished):
    """Closes 07:15; transfers stop at close. C1 is down 07:04-07:20. The restart comes after closing, so the
    transfer resumes at the next opening (day 2, 07:00; 20 t take 6 min) or stays suspended on a one-day run."""
    raw = copy.deepcopy(ONE_HOPPER)
    raw["hours"] = {"open": 7, "close": 7.25}
    raw["end_of_day"] = {"transfers_after_close": False}
    r, *_ = run(raw, [unload("Y1")], days=days, outages=[outage("C1", "07:04", "07:20")])
    t = r.transfers[0]
    assert t.finished == finished
    assert spans(t) == [(hm("07:04"), None if days == 1 else hm("07:00") + 24 * 60 * 60_000)]


# ---- loading ----

@pytest.mark.parametrize("down, finished", [(("07:08", "07:12"), "07:18"), (("07:02", "07:04"), "07:16")])
def test_a_load_pauses_and_resumes_and_the_stock_leaves_only_at_completion(down, finished):
    """L1 (30 t) loads from 07:00: 5 min setup + 9 min flow = 07:14. A stop of the reclaim conveyor R1 pauses the
    whole load clock (I4): 4 min during flow -> 07:18; 2 min during setup -> 07:16."""
    raw = copy.deepcopy(LOADING_SITE)
    raw["sequences"] = {"unload": ["tip"], "load": ["load"]}
    rows = [("L1", "load", "07:00", "YM", 30)]
    mid, *_ = run(raw, rows, until=hm("07:13"), outages=[outage("R1", *down)])
    assert (mid.bins["B1"][0], mid.dispatched_kg) == (100_000, 0)
    r, *_ = run(raw, rows, outages=[outage("R1", *down)])
    load = r.loads[0]
    assert (load.finished, spans(load), r.bins["B1"][0]) == (hm(finished), [(hm(down[0]), hm(down[1]))], 70_000)


# ---- configuration ----

@pytest.mark.parametrize("bad, words", [
    ([outage("H1", "08:00", "09:00")], "cannot be scheduled"),
    ([outage("ZZ", "08:00", "09:00")], "unknown equipment"),
    ([outage("C1", "09:00", "08:00")], "must end after"),
    ([outage("C1", "08:00", "09:00"), outage("C1", "08:30", "10:00")], "overlap"),
    ([outage("C1", "8 am", "09:00")], "HH:MM"),
])
def test_outages_are_validated(bad, words):
    raw = copy.deepcopy(ONE_HOPPER)
    raw["outages"] = bad
    with pytest.raises((ModelError, ConfigSchemaError)) as err:
        site = load_site_config(raw)
        TruckFlowModel(site, [], FixedServiceTimes({"tip": 1}), policy="feasible_first")
    assert words in str(err.value)


# ---- the audit checks the new invariants ----

def test_audit_detects_flow_through_unavailable_equipment():
    r, _, model = run(ONE_HOPPER, [unload("Y1")], outages=[outage("C1", "07:04", "07:08")])
    bad = copy.deepcopy(r)
    bad.transfers[0].interruptions.clear()  # pretend the stream kept flowing through the stopped conveyor
    problems = audit_flow(model.site, model.trucks, bad).problems
    assert any("while C1 was unavailable" in p for p in problems), problems


def test_audit_detects_a_route_reserved_during_an_outage():
    r, _, model = run(ONE_HOPPER, [unload("Y1")], outages=[outage("E1", "06:00", "07:05")])
    bad = copy.deepcopy(r)
    bad.transfers[0].started = hm("07:02")
    problems = audit_flow(model.site, model.trucks, bad).problems
    assert any("reserved" in p and "E1" in p for p in problems), problems
