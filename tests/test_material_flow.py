"""Grain-flow integrity (docs/MATERIAL_FLOW_AUDIT.md): hand-traced receiving-to-storage and storage-to-dispatch
cases, each checked by the engine's own balance and by the independent flow audit (`checks.flow_audit`).

Common figures: tipping 1 min; 30 t lots; elevators 200 t/h, so 30 t flows in 9 min; changeovers 0 min.
"""
import copy
import dataclasses
import json
from pathlib import Path

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config
from silo_engine.experiments.runner import kpis_of
from silo_engine.inputs.generated import generate_arrivals
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.random_streams import derived_seed
from silo_engine.sim.service_times import FixedServiceTimes, StochasticServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import TruckFlowModel
from test_loading import BASE as LOADING_SITE
from test_starvation_diagnostics import ONE_HOPPER, TWO_SHARED

COMMON = {"tip": 1, "load": 5}


def run(raw, rows, until=None, days=1):
    site = load_site_config(copy.deepcopy(raw))
    trucks = load_arrival_script({"trucks": [
        {"id": t, "activity": act, "arrive": at, "commodity": c, "tonnes": kg} for t, act, at, c, kg in rows]})
    r = TruckFlowModel(site, trucks, FixedServiceTimes(COMMON), policy="feasible_first", days=days).run(until)
    audit = audit_flow(site, trucks, r)
    assert r.material_balance_kg == 0 and r.violations == []
    assert audit.ok, audit.problems
    return r, audit, site, trucks


def unload(tid, at="07:00", c="YM", kg=30):
    return (tid, "unload", at, c, kg)


def two_yellow_bins(cap_first):
    raw = copy.deepcopy(ONE_HOPPER)
    raw["equipment"][3]["capT"] = cap_first  # B1 (yellow)
    raw["equipment"].append({"id": "B3", "type": "bin", "name": "B3", "capT": 1000, "commodities": ["YM"]})
    raw["edges"].append(["E1", "B3"])
    return raw


def test_unloading_completion_is_separate_from_storage_completion():
    """Y1 tips 07:00-07:01 and leaves at 07:01; its lot flows 07:01-07:10 and is in storage only then."""
    r, *_ = run(ONE_HOPPER, [unload("Y1")])
    lot = r.lots["L-Y1"]
    assert r.records[0].departed == hm("07:01")
    assert (lot.tipped_at, lot.first_transfer_at, lot.stored_at) == (hm("07:01"), hm("07:01"), hm("07:10"))
    assert (lot.stored_kg, lot.in_transit_kg, lot.in_pit_kg, lot.bins) == (30_000, 0, 0, ("B1",))
    assert kpis_of(r)["lots.mean_to_storage_min"] == 9


def test_stopped_mid_transfer_every_kilogram_is_located():
    """Stopped at 07:05: the truck has left, its 30 t are in transit (counted in the pit), nothing in the bin."""
    r, audit, *_ = run(ONE_HOPPER, [unload("Y1")], until=hm("07:05"))
    lot = r.lots["L-Y1"]
    assert (lot.stored_at, lot.stored_kg, lot.in_transit_kg, lot.in_pit_kg) == (None, 0, 30_000, 0)
    assert (r.pits["H1"], r.bins["B1"][0], r.received_kg) == (30_000, 0, 30_000)
    assert audit.in_transit == ["transfer H1/intake#1: 30000 kg H1 -> B1"]
    assert kpis_of(r)["lots.not_stored_t"] == 30


def test_lot_is_split_over_two_bins_when_the_first_fills():
    """B1 holds 20 t: 20 t flow 07:01-07:07 into B1, the other 10 t 07:07-07:10 into B3."""
    r, *_ = run(two_yellow_bins(20), [unload("Y1")])
    assert [(x.bin, x.kg, x.started, x.finished) for x in r.transfers] == [
        ("B1", 20_000, hm("07:01"), hm("07:07")), ("B3", 10_000, hm("07:07"), hm("07:10"))]
    assert (r.lots["L-Y1"].bins, r.lots["L-Y1"].stored_at) == (("B1", "B3"), hm("07:10"))
    assert (r.bins["B1"][0], r.bins["B3"][0]) == (20_000, 10_000)


def test_two_transfers_competing_for_the_last_space_in_a_bin():
    """Two independent lines both feed B1 (40 t). Y1 (H1) and Y2 (H2) tip 07:00-07:01. Y1's 30 t reserve B1 first;
    Y2 gets the remaining 10 t (07:01-07:04 on line 2), then its other 20 t go to B3 (07:04-07:10). B1 never holds
    or has reserved more than 40 t."""
    raw = copy.deepcopy(ONE_HOPPER)
    raw["equipment"] = [
        {"id": "H1", "type": "hopper", "name": "H1", "capT": 60, "rate": 400, "tip": [1, 1, 1], "commodities": ["YM"]},
        {"id": "H2", "type": "hopper", "name": "H2", "capT": 60, "rate": 400, "tip": [1, 1, 1], "commodities": ["YM"]},
        {"id": "C1", "type": "conveyor", "name": "C1", "rate": 300}, {"id": "E1", "type": "elevator", "name": "E1", "rate": 200},
        {"id": "C2", "type": "conveyor", "name": "C2", "rate": 300}, {"id": "E2", "type": "elevator", "name": "E2", "rate": 200},
        {"id": "B1", "type": "bin", "name": "B1", "capT": 40, "commodities": ["YM"]},
        {"id": "B3", "type": "bin", "name": "B3", "capT": 1000, "commodities": ["YM"]}]
    raw["commodities"] = raw["commodities"][:1]
    raw["edges"] = [["H1", "C1"], ["C1", "E1"], ["E1", "B1"], ["H2", "C2"], ["C2", "E2"], ["E2", "B1"], ["E2", "B3"]]
    r, *_ = run(raw, [unload("Y1"), unload("Y2")])
    assert sorted((x.lot_id, x.bin, x.kg, x.started, x.finished) for x in r.transfers) == [
        ("L-Y1", "B1", 30_000, hm("07:01"), hm("07:10")),
        ("L-Y2", "B1", 10_000, hm("07:01"), hm("07:04")),
        ("L-Y2", "B3", 20_000, hm("07:04"), hm("07:10"))]
    assert (r.bins["B1"][0], r.bins["B3"][0]) == (40_000, 20_000)


def test_grain_waits_in_the_pit_when_every_eligible_bin_is_full():
    """B1 holds 30 t and is the only yellow bin. Y1 fills it by 07:10. Y2 tipped 07:01-07:02, but its lot can never
    leave the pit: the run reports a stall with BIN_FULL, the lot stays in the pit, and the grain still balances."""
    raw = copy.deepcopy(ONE_HOPPER)
    raw["equipment"][3]["capT"] = 30
    r, *_ = run(raw, [unload("Y1"), unload("Y2")])
    assert r.stall is not None and r.stall.time == hm("07:10")
    assert [x.code for x in r.stall.waiting["H1/intake#2"]] == ["BIN_FULL"]
    lot = r.lots["L-Y2"]
    assert (lot.tipped_at, lot.stored_at, lot.in_pit_kg) == (hm("07:02"), None, 30_000)
    assert (r.bins["B1"][0], r.pits["H1"]) == (30_000, 30_000)


def test_shared_conveyor_is_held_for_its_clear_time_before_the_next_stream():
    """H1 and H2 share C1 (clear time 2 min). Y1 (H1) and W1 (H2) tip 07:00-07:01. Y1's lot holds the route
    07:01-07:10, released 07:12; W1's lot reserves it at 07:12, flows to 07:21, released 07:23."""
    raw = copy.deepcopy(TWO_SHARED)
    raw["equipment"][2]["clear_minutes"] = 2  # C1
    r, *_ = run(raw, [unload("Y1"), unload("W1", c="WM")])
    assert [(x.pit, x.started, x.finished, x.released) for x in r.transfers] == [
        ("H1", hm("07:01"), hm("07:10"), hm("07:12")), ("H2", hm("07:12"), hm("07:21"), hm("07:23"))]
    assert r.lots["L-W1"].stored_at == hm("07:21") and r.records[1].departed == hm("07:01")


@pytest.mark.parametrize("stop, dispatched, b1, in_transit", [
    ("07:12", 0, 100_000, ["load L1/load-route: 30000 kg B1 -> L1"]),
    ("07:20", 30_000, 70_000, ["transfer H1/intake#1: 30000 kg H1 -> B1"]),
])
def test_termination_during_loading_and_intake_on_a_shared_elevator(stop, dispatched, b1, in_transit):
    """Loading site: B1 opens with 100 t; E1 is shared by intake and load-out. L1 (30 t) starts loading at 07:00:
    5 min setup + 9 min flow, done 07:14. U1 tips 07:00-07:01; its lot waits for E1 and flows 07:14-07:23.
    Stopped at 07:12: the load is running (stock committed, not dispatched) and U1's lot is in the pit.
    Stopped at 07:20: 30 t dispatched, U1's lot in transit."""
    raw = copy.deepcopy(LOADING_SITE)
    raw["sequences"] = {"unload": ["tip"], "load": ["load"]}
    r, audit, *_ = run(raw, [("L1", "load", "07:00", "YM", 30), unload("U1")], until=hm(stop))
    assert (r.dispatched_kg, r.bins["B1"][0], r.pits["H1"]) == (dispatched, b1, 30_000)
    assert [x.id.split("/")[0] for x in r.loads] == ["L1"]
    assert audit.in_transit == [x.replace("L1/load-route", r.loads[0].id) for x in in_transit]
    full, *_ = run(raw, [("L1", "load", "07:00", "YM", 30), unload("U1")])
    assert (full.loads[0].finished, full.transfers[0].started, full.lots["L-U1"].stored_at) == (
        hm("07:14"), hm("07:14"), hm("07:23"))


def test_grain_left_in_the_pit_when_transfers_stop_at_close_on_the_last_day():
    """Closes 07:06 (no overtime), transfers stop at close, one day. Y1's lot (07:01-07:10) was already flowing and
    finishes; Y2's lot (tipped 07:01-07:02) is not sent and is still in the pit at the end."""
    raw = copy.deepcopy(ONE_HOPPER)
    raw["hours"] = {"open": 7, "close": 7.1}
    raw["end_of_day"] = {"transfers_after_close": False}
    r, audit, *_ = run(raw, [unload("Y1"), unload("Y2")])
    assert r.lots["L-Y1"].stored_at == hm("07:10")
    assert (r.lots["L-Y2"].stored_at, r.lots["L-Y2"].in_pit_kg, r.pits["H1"]) == (None, 30_000, 30_000)
    assert audit.in_transit == []


def test_opening_pit_grain_is_a_lot_without_a_truck():
    raw = copy.deepcopy(ONE_HOPPER)
    raw["equipment"][0].update({"level0": 20, "levelCommodity": "WM"})
    r, *_ = run(raw, [])
    lot = r.lots["L0-H1"]
    assert (lot.truck_id, lot.tipped_at, lot.commodity, lot.stored_at, lot.bins) == (None, None, "WM", hm("07:06"), ("B2",))


# ---- the audit itself must be able to fail ----

def _valid():
    r, _, site, trucks = run(two_yellow_bins(20), [unload("Y1"), unload("Y2")])
    return r, site, trucks


@pytest.mark.parametrize("corrupt, expected", [
    (lambda r: r.bins.__setitem__("B3", (r.bins["B3"][0] + 1, r.bins["B3"][1])), "bin B3"),
    (lambda r: r.pits.__setitem__("H1", 1), "pit H1"),
    (lambda r: r.transfers.append(dataclasses.replace(r.transfers[0], id="dup")), "moved out of"),
    (lambda r: r.transfers.__setitem__(0, dataclasses.replace(r.transfers[0], kg=r.transfers[0].kg + 5_000)), "exceeds"),
    (lambda r: r.transfers.__setitem__(0, dataclasses.replace(r.transfers[0], started=0)), "before lot"),
    (lambda r: r.transfers.__setitem__(1, dataclasses.replace(r.transfers[1], started=r.transfers[0].started)), "streams at"),
    (lambda r: r.transfers.__setitem__(0, dataclasses.replace(r.transfers[0], released=r.transfers[0].finished - 1)), "released"),
    (lambda r: setattr(r, "received_kg", r.received_kg + 1), "counters disagree"),
])
def test_the_flow_audit_detects_corrupted_records(corrupt, expected):
    r, site, trucks = _valid()
    bad = copy.deepcopy(r)
    corrupt(bad)
    problems = audit_flow(site, trucks, bad).problems
    assert any(expected in p for p in problems), problems


def test_audit_finds_nothing_wrong_on_generated_days():
    """Prototype demo sites A and B, both policies, extra demand: clean, nothing left in transit."""
    golden = {c["name"]: c for c in json.loads((Path(__file__).parent / "golden" / "validation_cases.json").read_text(encoding="utf-8"))["cases"]}
    for name in ("site_a_valid", "site_b_valid"):
        for policy in ("strict_fifo", "feasible_first"):
            site = load_site_config(copy.deepcopy(golden[name]["config"]))
            seed = derived_seed(9, "replication", 0)
            trucks = generate_arrivals(site, seed, days=1, demand_factor=1.3)
            r = TruckFlowModel(site, trucks, StochasticServiceTimes(site, seed), policy=policy).run()
            audit = audit_flow(site, trucks, r)
            assert audit.ok, (name, policy, audit.problems[:5])
            assert audit.checked["transfers"] > 50
