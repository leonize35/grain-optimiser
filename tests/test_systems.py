"""Systems: an optional grouping of equipment into silo systems (docs/PLATFORM_GAP_ANALYSIS.md step 2, gap G1).
A grouping only: it changes no simulation decision. Hand-traced. Test inputs, not site data.

Site: Silo A (HA -> CA -> EA -> BA) and Silo B (HB -> CB -> EB -> BB) from tests/test_unloading_labour.py, with 2
shared unloading workers (position 2 min, discharge 5 min, scrape 3 min). Trucks T1, T2, T3 at 07:00 (30 t each).
T1 unloads at HA and T2 at HB, 07:00-07:10; T3 waits for a hopper and unloads at HA 07:10-07:20.
"""
import copy

import pytest

from silo_engine.config import load_site_config
from silo_engine.config.report import prerun_report
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel
from test_unloading_labour import TIMES, site

SYSTEMS = [{"id": "A", "name": "Silo A", "equipment": ["HA", "CA", "EA", "BA"]},
           {"id": "B", "name": "Silo B", "equipment": ["HB", "CB", "EB", "BB"]}]


def raw(systems=SYSTEMS):
    r = site(workers=2)
    if systems is not None:
        r["systems"] = copy.deepcopy(systems)
    return r


def run(r, until=None):
    s = load_site_config(r)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": "07:00", "commodity": "YM", "tonnes": 30} for t in ("T1", "T2", "T3")]})
    return TruckFlowModel(s, script, TIMES, policy="feasible_first").run(until)


def test_trucks_are_attributed_to_the_system_of_their_hopper():
    o = run(raw()).outcomes
    assert {t: x["system"] for t, x in o["trucks"].items()} == {"T1": "A", "T2": "B", "T3": "A"}
    by = o["by_system"]
    assert by["A"]["unload"]["counts"]["completed"] == 2 and by["B"]["unload"]["counts"]["completed"] == 1
    assert (by["A"]["unload"]["tonnes"]["received_t"], by["B"]["unload"]["tonnes"]["received_t"]) == (60, 30)
    assert by["A"]["name"] == "Silo A"


def test_per_system_figures_sum_to_the_site_with_an_unassigned_group():
    """Stopped at 07:05: T1 and T2 are unloading (attributed to A and B); T3 has not reached a hopper (unassigned)."""
    o = run(raw(), until=hm("07:05")).outcomes
    by = o["by_system"]
    assert o["trucks"]["T3"]["system"] is None and by["unassigned"]["unload"]["counts"]["total"] == 1
    site_total = o["summary"]["unload"]
    for key in ("total", "completed", "unfinished_on_site"):
        assert sum(g["unload"]["counts"][key] for g in by.values() if "unload" in g) == site_total["counts"][key]
    minutes = sum(g["unload"]["occupancy"]["truck_minutes"] for g in by.values() if "unload" in g)
    assert minutes == site_total["occupancy"]["truck_minutes"] == 15  # three trucks x 5 min


def test_systems_change_no_simulation_decision():
    with_systems, without = run(raw()), run(raw(systems=None))
    assert [(e.time, e.label) for e in with_systems.trace] == [(e.time, e.label) for e in without.trace]
    assert "by_system" not in without.outcomes


@pytest.mark.parametrize("systems, words", [
    ([{"id": "A", "name": "Silo A", "equipment": ["HA", "GHOST"]}], "unknown equipment GHOST"),
    ([{"id": "A", "name": "A", "equipment": ["HA"]}, {"id": "B", "name": "B", "equipment": ["HA"]}], "in two systems"),
    ([{"id": "A", "name": "A", "equipment": ["HA"]}, {"id": "A", "name": "A2", "equipment": ["HB"]}], "share the id"),
])
def test_invalid_systems_are_refused(systems, words):
    with pytest.raises(ModelError) as err:
        run(raw(systems))
    assert words in str(err.value)


def test_report_findings_name_their_systems():
    r = raw()
    r["equipment"] = [e for e in r["equipment"] if e["id"] != "EA"]
    r["edges"] = [e for e in r["edges"] if "EA" not in e]  # HA's route to a bin is broken
    f = next(f for f in prerun_report(load_site_config(r)).findings if f.severity == "error" and "HA" in f.location)
    assert f.systems == ["A"]
    assert all(f.systems == [] for f in prerun_report(load_site_config(raw(systems=None))).findings)
