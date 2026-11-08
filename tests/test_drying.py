"""Drying from wet holding bins (rules confirmed by the user 2026-11-07). Hand-traced. Test inputs only.

- Moisture: each receiving truck has a moisture (percent), drawn per commodity from `demand.unload.moisture`
  [min, most likely, max] (its own random stream) or given in a script; it is measured at grading.
- `moisture_limits` {commodity: percent}: a load above the limit is wet. Wet loads go only to bins marked
  `wet_holding`; dry loads only to other bins. Assumption (to confirm): a pit holds wet or dry grain, not both.
- A drying move (a planned grain move with kind "drying" and a target moisture) takes grain from a bin through a
  `dryer` to another bin. The water removed is kg x (m - target) / (1 - target) for the bin's moisture m; it is a
  recorded loss (cause "moisture"). The dryer runs at its configured wet-grain rate (t/h), whatever the moisture.
- Each bin's moisture is tracked as water / stock; grain leaving a bin takes the bin's average moisture.

Site: sampler, grader (1 min each), hopper H1 (tip 5 min) -> C1 -> E1 -> WET1 (wet holding, 500 t) or DRY1 (5 000 t);
WET1 -> C2 -> D1 (dryer, 60 t/h = 1 t/min) -> E1. YM limit 14 %.
T1 (30 t at 18 %) and T2 (30 t at 12 %) arrive 07:00. T1 tips 07:02-07, drains into WET1 07:07-08. T2 is graded at
07:03, waits for the hopper and then for T1's wet grain to leave the pit, tips 07:08-13, drains into DRY1 07:13-14.
Drying move at 08:00, all of WET1 (30 t at 18 %) to 14 %: 08:00-08:30 through D1; 30 000 x 0.82 / 0.86 = 28 604.65,
so 28 605 kg reach DRY1 and 1 395 kg of water are removed. DRY1: 58 605 kg holding 3 600 + 4 004.7 kg of water.
"""
import copy

import pytest

from silo_engine.checks.flow_audit import audit_flow
from silo_engine.config import load_site_config
from silo_engine.config.rules_validation import validate_rules
from silo_engine.inputs.generated import generate_arrivals
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import TruckFlowModel

RAW = {
    "id": "drying", "name": "Drying test site", "version": 1, "hours": {"open": 7, "close": 18},
    "commodities": [{"id": "YM", "name": "Yellow maize"}],
    "equipment": [
        {"id": "S1", "type": "sampler", "name": "Sampler", "cap": 1, "time": [1, 1, 1]},
        {"id": "G1", "type": "grader", "name": "Grader", "cap": 1, "time": [1, 1, 1]},
        {"id": "H1", "type": "hopper", "name": "H1", "capT": 60, "rate": 1800, "tip": [5, 5, 5], "commodities": ["YM"]},
        {"id": "C1", "type": "conveyor", "name": "C1", "rate": 1800},
        {"id": "E1", "type": "elevator", "name": "E1", "rate": 1800},
        {"id": "C2", "type": "conveyor", "name": "Reclaim", "rate": 1800},
        {"id": "D1", "type": "grain_dryer", "name": "Dryer", "rate": 60},
        {"id": "WET1", "type": "bin", "name": "Wet bin", "capT": 500, "commodities": ["YM"], "wet_holding": True},
        {"id": "DRY1", "type": "bin", "name": "Dry bin", "capT": 5000, "commodities": ["YM"]}],
    "edges": [["H1", "C1"], ["C1", "E1"], ["E1", "WET1"], ["E1", "DRY1"], ["WET1", "C2"], ["C2", "D1"], ["D1", "E1"]],
    "sequences": {"unload": ["sample", "grade", "tip"]},
    "moisture_limits": {"YM": 14},
    "demand": {}, "changeovers": {"default_minutes": 0}}
DRY_MOVE = {"id": "dry1", "at": "08:00", "from_bin": "WET1", "to_bin": "DRY1", "kind": "drying", "target_moisture": 14}


def run(raw=RAW, moves=(DRY_MOVE,), trucks=(("T1", 18), ("T2", 12))):
    raw = copy.deepcopy(raw)
    raw["grain_moves"] = list(moves)
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": "07:00", "commodity": "YM", "tonnes": 30, "moisture": m}
        for t, m in trucks]})
    r = TruckFlowModel(s, script, FixedServiceTimes({"sample": 1, "grade": 1, "tip": 5}), policy="feasible_first").run()
    audit = audit_flow(s, script, r)
    assert r.violations == [] and r.material_balance_kg == 0 and r.stall is None
    assert audit.ok, audit.problems
    return r


def test_wet_loads_go_to_wet_holding_bins():
    r = run(moves=())
    assert {x.truck_id: (x.bin, x.started, x.finished) for x in r.transfers} == {
        "T1": ("WET1", hm("07:07"), hm("07:08")), "T2": ("DRY1", hm("07:13"), hm("07:14"))}
    assert (r.bins["WET1"][0], r.bins["DRY1"][0]) == (30000, 30000)
    assert (r.bin_moisture["WET1"], r.bin_moisture["DRY1"]) == (pytest.approx(18), pytest.approx(12))


def test_drying_from_the_wet_bin_removes_water():
    r = run()
    m = r.moves[0]
    assert (m.path, m.started, m.finished, m.kg, m.water_removed_kg, m.dryer) == (
        ["WET1", "C2", "D1", "E1", "DRY1"], hm("08:00"), hm("08:30"), 30000, 1395, "D1")
    assert (r.bins["WET1"][0], r.bins["DRY1"][0]) == (0, 58605)
    assert [(x.bin, x.kg, x.cause, x.time) for x in r.losses] == [("D1", 1395, "moisture", hm("08:30"))]
    assert r.bin_moisture["DRY1"] == pytest.approx(100 * (3600 + 28605 * 0.14) / 58605)
    assert r.bin_moisture["WET1"] is None  # empty


def test_grain_already_dry_enough_loses_no_water():
    r = run(moves=({**DRY_MOVE, "target_moisture": 20},))
    assert (r.moves[0].water_removed_kg, r.bins["DRY1"][0]) == (0, 60000)


def test_generated_moisture_per_commodity():
    raw = copy.deepcopy(RAW)
    raw["demand"] = {"unload": {"daily": 100, "mix": {"YM": 1}, "payload": [20, 25, 30]}}
    a = generate_arrivals(load_site_config(copy.deepcopy(raw)), seed=3)
    raw["demand"]["unload"]["moisture"] = {"YM": [11, 13, 20]}
    b = generate_arrivals(load_site_config(raw), seed=3)
    assert [(t.id, t.arrive_ms, t.kg) for t in a] == [(t.id, t.arrive_ms, t.kg) for t in b]
    assert all(t.moisture is None for t in a) and all(11 <= t.moisture <= 20 for t in b)


@pytest.mark.parametrize("change, words", [
    (lambda r: r["equipment"][7].pop("wet_holding"), "wet holding bin"),
    (lambda r: r["sequences"].update(unload=["sample", "tip", "grade"]), "graded before"),
    (lambda r: r["grain_moves"].append({"id": "m2", "at": "09:00", "from_bin": "WET1", "to_bin": "DRY1"}), "dryer"),
    (lambda r: r.update(moisture_limits={"YM": 140}), "between 0 and 100"),
])
def test_invalid_drying_setups_are_refused(change, words):
    raw = copy.deepcopy(RAW)
    raw["demand"] = {"unload": {"daily": 10, "mix": {"YM": 1}, "payload": [20, 25, 30], "moisture": {"YM": [11, 13, 20]}}}
    raw["grain_moves"] = [DRY_MOVE]
    change(raw)
    msgs = [i.msg for i in validate_rules(load_site_config(raw)).errors]
    assert any(words in m for m in msgs), msgs
