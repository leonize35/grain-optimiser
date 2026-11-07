"""TLS slice T2 (docs/TLS_ANALYSIS_DESIGN.md §3): wait causes and constraint candidates. Hand-traced; test inputs.

The run records, per clock hour, the truck-minutes of waiting per cause (`wait_causes`, reporting only). Each waiting
truck counts 1 per minute, split equally over its reasons. A reason is traced to what explains it:
- a pit without space -> its intake's reasons (e.g. a full bin), or, while it drains, the slowest part of the route;
- equipment whose lanes hold trucks that finished but are held there -> those trucks' own causes (BLOCKED);
- a truck held for its grading result -> the sample's queue reasons, or the grader serving it.
`constraint_candidates` sums the causes by the resource at the root of each chain and ranks them; the leader is named
the constraint only when it stands out (share and ratio settings, provisional), else "no single constraint".
"""
import copy

import pytest

from silo_engine.analysis.constraints import constraint_candidates
from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.truck_flow import TruckFlowModel
from test_grading_blocking import RAW as GRADING, run as grading_run
from test_outcomes_clearance import RAW, TIMES

RULE = [{"activity": "unload", "step": "weigh_in", "when": ["service_done", "graded"]}]


def total(r, kind="truck"):
    out: dict[str, float] = {}
    for cell in r.wait_causes.get(kind, {}).values():
        for k, v in cell.items():
            out[k] = out.get(k, 0) + v
    return out


def small_site(trucks, **eq_changes):
    raw = copy.deepcopy(RAW)
    raw["hours"] = {"open": 7, "close": 18}
    eq = {e["id"]: e for e in raw["equipment"]}
    for k, v in eq_changes.items():
        eid, field = k.split("__")
        eq[eid][field] = v
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": a, "commodity": "YM", "tonnes": 30} for t, a in trucks]})
    return s, TruckFlowModel(s, script, TIMES, policy="feasible_first").run()


def test_waiting_behind_trucks_held_for_grading_traces_to_the_grader():
    """Sampler 4 min, one grader 10 min, WB_IN held until graded. T2 waits for WB_IN 07:08-07:14 while T1 is held
    there (6 min, traced) ; T3 waits 07:12-07:24: T1 held 07:12-07:14 (2, traced), T2 weighing 07:14-07:16 (2, the
    bridge itself), T2 held 07:16-07:24 (8, traced). Held trucks: T1 07:06-14, T2 07:16-24, T3 07:26-34 (24).
    Sampler: T2 07:01-04, T3 07:02-08 (9). Samples wait for the grader: 6 + 12 = 18."""
    r = grading_run([("T1", "07:00"), ("T2", "07:01"), ("T3", "07:02")], release_rules=RULE)
    assert total(r) == {"EQUIPMENT_BUSY:S1": 9, "EQUIPMENT_BUSY:WB_IN": 2, "IN_SERVICE:G1#0<RELEASE:graded": 24,
                        "IN_SERVICE:G1#0<RELEASE:graded<BLOCKED:WB_IN": 16}
    assert total(r, "sample") == {"EQUIPMENT_BUSY:G1": 18}
    c = constraint_candidates(load_site_config(copy.deepcopy({**GRADING, "release_rules": RULE})), r)
    assert c["total_truck_min"] == 51
    assert [(x["id"], x["truck_min"]) for x in c["candidates"]] == [("G1", 40), ("S1", 9), ("WB_IN", 2)]
    g1 = c["candidates"][0]
    assert (g1["kind"], g1["direct_min"], g1["via"]) == (
        "grader", 0, {"RELEASE:graded": 24, "RELEASE:graded<BLOCKED:WB_IN": 16})
    assert g1["share"] == pytest.approx(40 / 51)
    assert c["constraint"] == "G1"


def test_a_full_pit_traces_to_the_draining_route():
    """Hopper H1 holds one load (30 t); belt C1 180 t/h (30 t in 10 min). T2 waits for the tipping lane 07:04-07:07
    (T1 tipping) and then for pit space while T1's grain drains over C1 07:07-07:17."""
    _, r = small_site([("T1", "07:00"), ("T2", "07:00")], H1__capT=30, C1__rate=180)
    assert total(r) == {"EQUIPMENT_BUSY:WB_IN": 2, "EQUIPMENT_BUSY:H1:tip": 3, "FLOW:C1<PIT_SPACE:H1": 10}


def test_a_full_pit_traces_to_a_full_bin():
    """Pit 30 t, bin B1 30 t, all rates 1800 t/h (a load drains in 1 min; on a tie the pit's own discharge is named).
    T1 tips 07:02-07, drains 07:07-08 (bin now full). T2 waits for the lane 07:04-07 and pit space 07:07-08, tips
    07:08-13; its grain cannot leave the pit (bin full). T3 waits: lane 07:06-07, pit space (draining) 07:07-08, lane
    07:08-13, pit space (bin full) 07:13 until the run stalls at 07:15."""
    s, r = small_site([("T1", "07:00"), ("T2", "07:00"), ("T3", "07:00")], H1__capT=30, B1__capT=30)
    assert total(r) == {"EQUIPMENT_BUSY:WB_IN": 6, "EQUIPMENT_BUSY:H1:tip": 9, "FLOW:H1<PIT_SPACE:H1": 2,
                        "BIN_FULL:B1<PIT_SPACE:H1": 2}
    assert total(r, "grain") == {"BIN_FULL:B1": 2}
    c = constraint_candidates(s, r)
    assert [(x["id"], x["truck_min"]) for x in c["candidates"]] == [("H1", 11), ("WB_IN", 6), ("B1", 2)]
    assert c["candidates"][2]["via"] == {"PIT_SPACE:H1": 2}
    assert c["constraint"] == "H1"  # 11/19 = 58 % of waiting, 1.8 x the next


def test_no_single_constraint_when_nothing_stands_out():
    """WB_IN 2 and H1 3 truck-minutes: H1 has 60 %, 1.5 x the next; with a required ratio of 2 nothing stands out."""
    s, r = small_site([("T1", "07:00"), ("T2", "07:00")])
    assert constraint_candidates(s, r)["constraint"] == "H1"
    c = constraint_candidates(s, r, lead_ratio=2)
    assert c["constraint"] is None and "no single constraint" in c["verdict"]
    assert (c["settings"]["lead_share"], c["settings"]["lead_ratio"]) == (0.4, 2)


def test_the_leading_cause_can_change_during_the_day():
    """T1, T2 arrive 07:58: T2 waits for WB_IN 07:58-08:00 (hour 7) and for the hopper 08:02-08:05 (hour 8)."""
    s, r = small_site([("T1", "07:58"), ("T2", "07:58")])
    c = constraint_candidates(s, r, min_hour_min=1)
    assert [(h["day"], h["hour"], h["leader"], h["truck_min"]) for h in c["by_hour"]] == [
        (1, 7, "WB_IN", 2), (1, 8, "H1", 3)]
    assert c["shifts"] == [{"from": "day 1 07:00", "to": "day 1 08:00", "leader": "WB_IN"},
                           {"from": "day 1 08:00", "to": "day 1 09:00", "leader": "H1"}]


def test_waiting_during_partial_tipping_counts_as_in_service():
    """tests/test_partial_tipping.py: 40 t into a 30 t pit draining at 1 t/min (hopper discharge 60 t/h, the slowest
    part of the route). Tipping 07:00-07:17:45 of which 10 min tipping: 7.75 min waiting on the hopper for space."""
    from test_partial_tipping import RAW as P, run as prun
    r = prun(copy.deepcopy(P))
    assert total(r, "in_service") == {"FLOW:H1<PIT_SPACE:H1": 7.75}
    assert "truck" not in r.wait_causes
    c = constraint_candidates(load_site_config(copy.deepcopy(P)), r)
    assert (c["in_service_min"], c["candidates"][0]["id"], c["candidates"][0]["in_service_min"]) == (7.75, "H1", 7.75)


@pytest.mark.parametrize("case", ["grading", "bin_full", "partial"])
def test_truck_waiting_causes_reconcile_with_the_step_records(case):
    if case == "grading":
        s = load_site_config(copy.deepcopy(GRADING))
        r = grading_run([("T1", "07:00"), ("T2", "07:01"), ("T3", "07:02")], release_rules=RULE)
    elif case == "bin_full":
        s, r = small_site([("T1", "07:00"), ("T2", "07:00"), ("T3", "07:00")], H1__capT=30, B1__capT=30)
    else:
        from test_partial_tipping import RAW as P, run as prun
        s, r = load_site_config(copy.deepcopy(P)), prun(copy.deepcopy(P), trucks=(("T1", "07:00", 40), ("T2", "07:01", 20)))
    assert constraint_candidates(s, r)["reconciled"] is True
