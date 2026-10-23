"""Verification of the starvation and overtaking diagnostics (Q1 reporting) on hand-traced arrival sequences.

Definitions under test (TruckMetrics docstring):
- Truck X overtakes truck Y when X *starts* a step while Y is still waiting in the same queue group, Y entered
  that queue first, and Y arrived at the gate first (equal arrival times keep script order).
- Admission order (start of tipping) is what counts; completion order (departure) does not.
- At a site with several hoppers the hopper queue is one queue: a later truck admitted to *any* hopper while an
  earlier truck waits counts, even when the waiting truck could not have used that hopper.

All sites: tipping 1 min unless overridden; 30 t lots; elevators 200 t/h (30 t flows in 9 min); hoppers hold
60 t; changeovers 0 min.
"""
import copy

from silo_engine.config import load_site_config
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import TruckFlowModel

COMMODITIES = [{"id": "YM", "name": "Yellow maize"}, {"id": "WM", "name": "White maize"}]
BINS = [{"id": "B1", "type": "bin", "name": "B1", "capT": 1000, "commodities": ["YM"]},
        {"id": "B2", "type": "bin", "name": "B2", "capT": 1000, "commodities": ["WM"]}]


def hopper(hid, commodities=("YM", "WM")):
    return {"id": hid, "type": "hopper", "name": hid, "capT": 60, "rate": 400, "tip": [1, 1, 1],
            "commodities": list(commodities)}


def site(equipment, edges, **extra):
    raw = {"id": "d", "name": "Diagnostics silo", "version": 1, "hours": {"open": 7, "close": 18},
           "commodities": COMMODITIES, "equipment": equipment + BINS, "edges": edges,
           "sequences": {"unload": ["tip"]}, "demand": {}, "changeovers": {"default_minutes": 0}}
    raw.update(extra)
    return raw


ONE_HOPPER = site([hopper("H1"), {"id": "C1", "type": "conveyor", "name": "C1", "rate": 300},
                   {"id": "E1", "type": "elevator", "name": "E1", "rate": 200}],
                  [["H1", "C1"], ["C1", "E1"], ["E1", "B1"], ["E1", "B2"]])
# Two hoppers with their own conveyor and elevator each; H2 takes yellow maize only.
TWO_INDEPENDENT = site([hopper("H1"), hopper("H2", ["YM"]),
                        {"id": "C1", "type": "conveyor", "name": "C1", "rate": 300},
                        {"id": "E1", "type": "elevator", "name": "E1", "rate": 200},
                        {"id": "C2", "type": "conveyor", "name": "C2", "rate": 300},
                        {"id": "E2", "type": "elevator", "name": "E2", "rate": 200}],
                       [["H1", "C1"], ["C1", "E1"], ["E1", "B1"], ["E1", "B2"],
                        ["H2", "C2"], ["C2", "E2"], ["E2", "B1"]])
TWO_BOTH_COMMODITIES = copy.deepcopy(TWO_INDEPENDENT)
TWO_BOTH_COMMODITIES["equipment"][1]["commodities"] = ["YM", "WM"]
TWO_BOTH_COMMODITIES["edges"].append(["E2", "B2"])
# Two hoppers sharing one conveyor and elevator.
TWO_SHARED = site([hopper("H1"), hopper("H2"), {"id": "C1", "type": "conveyor", "name": "C1", "rate": 300},
                   {"id": "E1", "type": "elevator", "name": "E1", "rate": 200}],
                  [["H1", "C1"], ["H2", "C1"], ["C1", "E1"], ["E1", "B1"], ["E1", "B2"]])


def run(raw, trucks, policy="feasible_first", tip_overrides=None, until=None, days=1):
    script = load_arrival_script({"trucks": [
        {"id": tid, "activity": "unload", "arrive": t, "commodity": c, "tonnes": kg}
        for tid, t, c, kg in trucks]})
    model = TruckFlowModel(load_site_config(copy.deepcopy(raw)), script,
                           FixedServiceTimes({"tip": 1}, {(tid, "tip"): v for tid, v in (tip_overrides or {}).items()}),
                           policy=policy, days=days)
    return model.run(until)


def table(result, *fields):
    return {t: tuple(getattr(x, f) for f in fields) for t, x in result.truck_metrics.items()}


def admission_order(result):
    return [t for t, x in sorted(result.truck_metrics.items(), key=lambda kv: kv[1].hopper_admitted)]


def completion_order(result):
    return [t for t, x in sorted(result.truck_metrics.items(), key=lambda kv: kv[1].departed)]


YW_Y = [("Y1", "07:00", "YM", 30), ("W1", "07:00", "WM", 30), ("Y2", "07:00", "YM", 30)]


def test_every_receiving_truck_records_the_required_fields():
    """Feasible-first, one hopper (hand trace in test_fairness.py): Y1 tips 07:00, Y2 overtakes W1 at 07:01,
    W1 tips at 07:19 once the pit has emptied."""
    m = run(ONE_HOPPER, YW_Y).truck_metrics["W1"]
    assert (m.commodity, m.grade, m.arrived, m.gate_admitted) == ("WM", None, hm("07:00"), hm("07:00"))
    assert m.queue_entered == {"tip": hm("07:00")}
    assert (m.hopper_queue_entered, m.hopper_admitted, m.departed) == (hm("07:00"), hm("07:19"), hm("07:20"))
    assert (m.total_waiting_min, m.hopper_wait_min) == (19, 19)
    assert (m.overtaken_by_later, m.overtaken_at_hopper, m.status, m.starved) == (1, 1, "completed", False)


def test_strict_fifo_never_overtakes():
    """Strict FIFO: W1 blocks Y2. Y1 tips 07:00-07:01 (lot flows 07:01-07:10); W1 waits for the empty pit and
    tips 07:10-07:11 (lot flows 07:11-07:20); Y2 waits behind W1, then for the empty pit, and tips 07:20-07:21."""
    r = run(ONE_HOPPER, YW_Y, policy="strict_fifo")
    assert table(r, "hopper_admitted", "total_waiting_min", "overtaken_by_later") == {
        "Y1": (hm("07:00"), 0, 0), "W1": (hm("07:10"), 10, 0), "Y2": (hm("07:20"), 20, 0)}
    assert admission_order(r) == completion_order(r) == ["Y1", "W1", "Y2"]
    assert r.fairness["unload"].max_overtaken == 0


def test_feasible_first_with_incompatible_commodities_counts_one_overtake():
    r = run(ONE_HOPPER, YW_Y)
    assert table(r, "hopper_admitted", "total_waiting_min", "overtaken_by_later") == {
        "Y1": (hm("07:00"), 0, 0), "W1": (hm("07:19"), 19, 1), "Y2": (hm("07:01"), 1, 0)}
    assert admission_order(r) == ["Y1", "Y2", "W1"]


def test_two_hoppers_finishing_out_of_order_is_not_overtaking():
    """Both hoppers take both maizes. A (yellow, tips 10 min) takes H1 07:00-07:10. W (white, 20 t) takes H2
    07:00-07:01; its lot flows 07:01-07:07. B (yellow) finds H1 busy and white grain in H2; it tips into H2 when
    that pit empties, 07:07-07:08. Admission order A, W, B; completion order W, B, A. Nobody was overtaken."""
    r = run(TWO_BOTH_COMMODITIES, [("A", "07:00", "YM", 30), ("W", "07:00", "WM", 20), ("B", "07:00", "YM", 30)],
            tip_overrides={"A": 10})
    assert admission_order(r) == ["A", "W", "B"]
    assert completion_order(r) == ["W", "B", "A"]
    assert table(r, "hopper_admitted", "departed", "overtaken_by_later") == {
        "A": (hm("07:00"), hm("07:10"), 0), "W": (hm("07:00"), hm("07:01"), 0), "B": (hm("07:07"), hm("07:08"), 0)}


def test_later_truck_admitted_to_another_hopper_counts_as_overtaking():
    """H2 takes yellow maize only. A (yellow, tips 10 min) takes H1 07:00-07:10. W (white) can use H1 only: it
    waits. B (yellow, arrived after W) tips into H2 07:00-07:01 while W waits: one overtake for W, although W could
    not have used H2. A's lot flows from H1 07:10-07:19; W tips 07:19-07:20."""
    r = run(TWO_INDEPENDENT, [("A", "07:00", "YM", 30), ("W", "07:00", "WM", 30), ("B", "07:00", "YM", 30)],
            tip_overrides={"A": 10})
    assert table(r, "hopper_admitted", "total_waiting_min", "overtaken_at_hopper") == {
        "A": (hm("07:00"), 0, 0), "W": (hm("07:19"), 19, 1), "B": (hm("07:00"), 0, 0)}
    assert admission_order(r)[:2] == ["A", "B"] and admission_order(r)[2] == "W"


def test_shared_downstream_equipment_blocking_a_hopper():
    """H1 and H2 share C1/E1. Y1 tips into H1 07:00-07:01; its lot holds C1 07:01-07:10. W1 tips into H2
    07:00-07:01, but its lot cannot flow until C1 is free (07:10-07:19, oldest grain first). Y2 tips into H1
    07:01-07:02. Y3 arrives 07:03: H1 lacks space until Y1's lot has gone (07:10) and H2 holds white grain, so Y3
    waits. W2 arrives 07:04 and tips into H2 (30 t free) 07:04-07:05 while Y3 waits: Y3 is overtaken once.
    Y3 tips into H1 07:10-07:11."""
    r = run(TWO_SHARED, [("Y1", "07:00", "YM", 30), ("W1", "07:00", "WM", 30), ("Y2", "07:00", "YM", 30),
                         ("Y3", "07:03", "YM", 30), ("W2", "07:04", "WM", 30)])
    assert table(r, "hopper_admitted", "total_waiting_min", "overtaken_by_later") == {
        "Y1": (hm("07:00"), 0, 0), "W1": (hm("07:00"), 0, 0), "Y2": (hm("07:01"), 1, 0),
        "Y3": (hm("07:10"), 7, 1), "W2": (hm("07:04"), 0, 0)}
    assert [t.pit for t in r.transfers][:2] == ["H1", "H2"]  # W1's white lot waited for the shared conveyor
    assert r.transfers[1].started == hm("07:10")


def test_truck_still_waiting_at_the_end_of_the_operating_day():
    """Strict FIFO as above, but the plant stops at 07:15 (close, no overtime) on the only day. Y2 never tips:
    unfinished, waiting counted to the hard stop (15 min). W1 tipped 07:10-07:11 and left."""
    raw = copy.deepcopy(ONE_HOPPER)
    raw["hours"] = {"open": 7, "close": 7.25}
    r = run(raw, YW_Y, policy="strict_fifo")
    y2 = r.truck_metrics["Y2"]
    assert (y2.status, y2.unfinished, y2.hopper_admitted, y2.departed) == ("unfinished", True, None, None)
    assert (y2.total_waiting_min, y2.hopper_wait_min, y2.hopper_queue_entered) == (15, 15, hm("07:00"))
    assert r.truck_metrics["W1"].status == "completed"
    assert r.fairness["unload"].by_commodity["YM"].still_waiting == 1
    assert r.summary["unload"].unfinished == 1


def _decisions(result):
    trace = [(e.time, e.priority, e.seq, e.label, e.cancelled) for e in result.trace]  # callbacks differ per run
    return (trace, result.transfers, result.loads, result.records, result.received_kg, result.summary,
            result.overtaken)


def test_starvation_threshold_changes_only_the_classification():
    cases = [(ONE_HOPPER, YW_Y, {}),
             (TWO_SHARED, [("Y1", "07:00", "YM", 30), ("W1", "07:00", "WM", 30), ("Y2", "07:00", "YM", 30),
                           ("Y3", "07:03", "YM", 30), ("W2", "07:04", "WM", 30)], {})]
    for raw, trucks, _ in cases:
        runs = []
        for fairness in ({"starvation_wait_minutes": 0}, {"starvation_wait_minutes": 5},
                         {"starvation_wait_minutes": 10_000}, {"starvation_wait_minutes": 10_000, "starvation_overtakes": 1}):
            changed = copy.deepcopy(raw)
            changed["fairness"] = fairness
            runs.append(run(changed, trucks))
        assert all(_decisions(x) == _decisions(runs[0]) for x in runs[1:])
        strip = lambda r: {t: (m.total_waiting_min, m.overtaken_by_later, m.status) for t, m in r.truck_metrics.items()}  # noqa: E731
        assert all(strip(x) == strip(runs[0]) for x in runs[1:])
        starved = [sum(m.starved for m in x.truck_metrics.values()) for x in runs]
        assert starved[0] == len(trucks) and starved[2] == 0  # threshold 0: everyone; 10 000 min: nobody
        assert starved[3] == sum(m.overtaken_by_later >= 1 for m in runs[3].truck_metrics.values()) == 1


def test_per_commodity_distribution_figures():
    """TWO_SHARED case: yellow waits 0, 1, 7 -> mean 8/3, median 1, p95 7 (nearest rank), max 7."""
    r = run(TWO_SHARED, [("Y1", "07:00", "YM", 30), ("W1", "07:00", "WM", 30), ("Y2", "07:00", "YM", 30),
                         ("Y3", "07:03", "YM", 30), ("W2", "07:04", "WM", 30)])
    ym = r.fairness["unload"].by_commodity["YM"]
    assert (ym.trucks, ym.median_total_wait_min, ym.p95_total_wait_min, ym.max_total_wait_min) == (3, 1, 7, 7)
    assert abs(ym.mean_total_wait_min - 8 / 3) < 1e-12
    assert (ym.max_overtaken, ym.max_overtaken_at_hopper, ym.mean_overtaken, ym.starved) == (1, 1, 1 / 3, 0)


def test_starvation_threshold_leaves_a_generated_day_unchanged():
    """Prototype Site A, generated arrivals and stochastic times, both policies: thresholds 0 and 10 000 min give
    identical decisions and waits."""
    import json
    from pathlib import Path

    from silo_engine.inputs.generated import generate_arrivals
    from silo_engine.sim.service_times import StochasticServiceTimes
    golden = {c["name"]: c for c in json.loads((Path(__file__).parent / "golden" / "validation_cases.json").read_text(encoding="utf-8"))["cases"]}
    for policy in ("strict_fifo", "feasible_first"):
        out = []
        for minutes in (0, 10_000):
            raw = copy.deepcopy(golden["site_a_valid"]["config"])
            raw["fairness"] = {"starvation_wait_minutes": minutes}
            s = load_site_config(raw)
            r = TruckFlowModel(s, generate_arrivals(s, 11, days=1, demand_factor=1.2), StochasticServiceTimes(s, 11),
                               policy=policy).run()
            out.append((r, _decisions(r), {t: (m.total_waiting_min, m.overtaken_by_later) for t, m in r.truck_metrics.items()}))
        assert out[0][1:] == out[1][1:]
        assert sum(m.starved for m in out[0][0].truck_metrics.values()) == len(out[0][0].truck_metrics)
        assert sum(m.starved for m in out[1][0].truck_metrics.values()) == 0


def test_queue_entry_order_and_gate_arrival_order_must_both_hold():
    """Ambiguity case: P arrived at the gate before Q but reached the hopper queue after Q (slow weighing).
    Weighbridge with 2 lanes, weigh-in then tip. Y0 (yellow) arrives 07:00, weighs 07:00-07:01, tips 07:01-07:02;
    its lot flows 07:02-07:11. P (yellow) arrives 07:00 and weighs 5 min, 07:00-07:05. Q (white) arrives 07:01,
    weighs 07:01-07:02 and joins the hopper queue at 07:02, but the pit holds yellow grain. P joins at 07:05 and
    tips 07:05-07:06 ahead of Q. Under the current definition this is NOT an overtake of Q, because P arrived at
    the gate first. P's lot flows 07:11-07:20; Q tips 07:20-07:21."""
    raw = copy.deepcopy(ONE_HOPPER)
    raw["equipment"].append({"id": "WB1", "type": "weighbridge", "name": "Weighbridge", "cap": 2, "time": [1, 1, 1]})
    raw["sequences"] = {"unload": ["weigh_in", "tip"]}
    script = load_arrival_script({"trucks": [
        {"id": tid, "activity": "unload", "arrive": t, "commodity": c, "tonnes": 30}
        for tid, t, c in (("Y0", "07:00", "YM"), ("P", "07:00", "YM"), ("Q", "07:01", "WM"))]})
    model = TruckFlowModel(load_site_config(raw), script,
                           FixedServiceTimes({"tip": 1, "weigh_in": 1}, {("P", "weigh_in"): 5}), policy="feasible_first")
    r = model.run()
    assert table(r, "hopper_queue_entered", "hopper_admitted", "overtaken_by_later") == {
        "Y0": (hm("07:01"), hm("07:01"), 0), "P": (hm("07:05"), hm("07:05"), 0), "Q": (hm("07:02"), hm("07:20"), 0)}
    assert r.truck_metrics["Q"].queue_entered == {"weigh_in": hm("07:01"), "tip": hm("07:02")}
    assert (r.truck_metrics["Q"].total_waiting_min, r.truck_metrics["Q"].hopper_wait_min) == (18, 18)
    assert ("Q/tip", "P/tip") in model.dispatcher.overtake_log  # seen in queue order, filtered by arrival order


def test_overtakes_at_the_load_point_are_not_hopper_overtakes():
    """Loading site (test_loading.py): bin B1 holds 100 t. LA orders 110 t at 07:00 and waits for stock. LB
    (30 t, arrived after LA) loads 07:00-07:14 (5 min setup + 9 min): LA overtaken once, at the load point.
    U tips 40 t at 07:30, flowing 07:31-07:43; LA loads from 07:43."""
    from test_loading import BASE
    raw = copy.deepcopy(BASE)
    raw["sequences"] = {"unload": ["tip"], "load": ["load"]}
    script = load_arrival_script({"trucks": [
        {"id": "LA", "activity": "load", "arrive": "07:00", "commodity": "YM", "tonnes": 110},
        {"id": "LB", "activity": "load", "arrive": "07:00", "commodity": "YM", "tonnes": 30},
        {"id": "U", "activity": "unload", "arrive": "07:30", "commodity": "YM", "tonnes": 40}]})
    r = TruckFlowModel(load_site_config(raw), script, FixedServiceTimes({"tip": 1, "load": 5}),
                       policy="feasible_first").run()
    assert r.stall is None and r.material_balance_kg == 0
    la = r.truck_metrics["LA"]
    assert (la.overtaken_by_later, la.overtaken_at_hopper, la.hopper_queue_entered, la.hopper_admitted) == (1, 0, None, None)
    assert (la.queue_entered, la.total_waiting_min, la.hopper_wait_min) == ({"load": hm("07:00")}, 43, None)


def test_percentiles_use_nearest_rank_on_a_generated_day():
    import json
    import math
    from pathlib import Path

    from silo_engine.inputs.generated import generate_arrivals
    from silo_engine.sim.service_times import StochasticServiceTimes
    golden = {c["name"]: c for c in json.loads((Path(__file__).parent / "golden" / "validation_cases.json").read_text(encoding="utf-8"))["cases"]}
    s = load_site_config(copy.deepcopy(golden["site_a_valid"]["config"]))
    r = TruckFlowModel(s, generate_arrivals(s, 5, days=1, demand_factor=1.2), StochasticServiceTimes(s, 5),
                       policy="feasible_first").run()
    for c, cf in r.fairness["unload"].by_commodity.items():
        waits = sorted(m.total_waiting_min for m in r.truck_metrics.values() if m.activity == "unload" and m.commodity == c)
        assert len(waits) >= 20 or c != "YM"  # yellow maize has enough trucks to tell percentiles apart
        assert cf.p95_total_wait_min == waits[math.ceil(0.95 * len(waits)) - 1]
        assert cf.median_total_wait_min == waits[math.ceil(0.5 * len(waits)) - 1]
