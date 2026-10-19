"""Scripted truck arrivals: an explicit list of trucks for deterministic, hand-checkable tests and replays."""
import copy
import json
from pathlib import Path

import pytest

from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import ScriptError, load_arrival_script, schedule_arrivals, check_script_against_site
from silo_engine.sim.calendar import ARRIVAL, CONTROL, Calendar
from silo_engine.sim.time import hm

SITE_A = json.loads((Path(__file__).parent / "golden" / "validation_cases.json").read_text(encoding="utf-8"))["cases"][0]["config"]

SCRIPT = {
    "trucks": [
        {"id": "U1", "activity": "unload", "arrive": "07:00", "commodity": "YM", "tonnes": "32.125"},
        {"id": "W1", "activity": "weigh", "arrive": "07:00"},
        {"id": "L1", "activity": "load", "arrive": "06:45", "commodity": "YM", "tonnes": 34},
        {"id": "U0", "activity": "unload", "arrive": "06:00", "commodity": "WM", "tonnes": "30.5", "backlog": True},
    ]
}


def test_script_is_parsed_into_exact_times_and_kilograms():
    trucks = load_arrival_script(SCRIPT)
    u1 = next(t for t in trucks if t.id == "U1")
    assert u1.arrive_ms == hm("07:00")
    assert u1.kg == 32_125
    assert u1.commodity == "YM"
    w1 = next(t for t in trucks if t.id == "W1")
    assert w1.kg is None and w1.commodity is None


def test_arrivals_are_scheduled_in_hand_derived_order():
    # 06:00 U0 (backlog, CONTROL priority), 06:45 L1, 07:00 U1 then W1 (same time: script order).
    cal = Calendar()
    seen: list[tuple[str, str]] = []
    schedule_arrivals(cal, load_arrival_script(SCRIPT), lambda c, truck: seen.append((c.now, truck.id)))
    cal.run()
    assert seen == [(hm("06:00"), "U0"), (hm("06:45"), "L1"), (hm("07:00"), "U1"), (hm("07:00"), "W1")]
    assert [e.priority for e in cal.log] == [CONTROL, ARRIVAL, ARRIVAL, ARRIVAL]


def test_duplicate_truck_ids_are_refused():
    s = copy.deepcopy(SCRIPT)
    s["trucks"][1]["id"] = "U1"
    with pytest.raises(ScriptError, match="U1"):
        load_arrival_script(s)


def test_grain_trucks_need_commodity_and_tonnes_and_weigh_only_trucks_carry_none():
    missing = {"trucks": [{"id": "U9", "activity": "unload", "arrive": "07:00", "commodity": "YM"}]}
    with pytest.raises(ScriptError, match="U9"):
        load_arrival_script(missing)
    extra = {"trucks": [{"id": "W9", "activity": "weigh", "arrive": "07:00", "tonnes": 30}]}
    with pytest.raises(ScriptError, match="W9"):
        load_arrival_script(extra)


def test_bad_time_or_tonnage_is_reported_with_the_truck_id():
    with pytest.raises(ScriptError, match="U7"):
        load_arrival_script({"trucks": [{"id": "U7", "activity": "unload", "arrive": "7h00", "commodity": "YM", "tonnes": 30}]})
    with pytest.raises(ScriptError, match="U8"):
        load_arrival_script({"trucks": [{"id": "U8", "activity": "unload", "arrive": "07:00", "commodity": "YM", "tonnes": "30.0001"}]})


def test_script_is_checked_against_the_site_in_manager_language():
    site = load_site_config(SITE_A)
    assert check_script_against_site(load_arrival_script(SCRIPT), site) == []
    s = copy.deepcopy(SCRIPT)
    s["trucks"][0]["commodity"] = "SORGHUM"
    s["trucks"][2]["arrive"] = "19:30"
    problems = check_script_against_site(load_arrival_script(s), site)
    assert problems == [
        "Truck U1 brings SORGHUM, which is not a commodity at Kareepan Silo.",
        "Truck L1 arrives at 19:30, after the site closes at 18:00.",
    ]
