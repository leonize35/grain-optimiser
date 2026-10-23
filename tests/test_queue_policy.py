"""Queue-policy architecture (docs/QUEUE_POLICY_DESIGN.md): a common policy interface, per-site and per-experiment
selection, and the reporting fields for the six domain decisions of 2026-10-23. No new scheduling intervention.

Sites and hand traces reuse tests/test_starvation_diagnostics.py (tipping 1 min, 30 t lots flow 9 min, hoppers
hold 60 t, changeovers 0 min).
"""
import copy
import dataclasses
import json
from pathlib import Path

import pytest

from silo_engine.config import ConfigSchemaError, load_site_config
from silo_engine.config.schema import config_hash
from silo_engine.experiments.runner import run_experiment
from silo_engine.inputs.scripted import load_arrival_script
from silo_engine.sim.dispatcher import Dispatcher, DispatcherError, WaitReason
from silo_engine.sim.queue_policy import FeasibleFirst, Recommendation, StrictFifo, WaitingRequest
from silo_engine.sim.service_times import FixedServiceTimes
from silo_engine.sim.time import hm
from silo_engine.sim.truck_flow import TruckFlowModel
from test_dispatcher import Gate
from test_starvation_diagnostics import ONE_HOPPER, TWO_INDEPENDENT, YW_Y, _decisions, run, table

GOLDEN = {c["name"]: c for c in json.loads((Path(__file__).parent / "golden" / "validation_cases.json").read_text(encoding="utf-8"))["cases"]}
A_W_B = [("A", "07:00", "YM", 30), ("W", "07:00", "WM", 30), ("B", "07:00", "YM", 30)]


# ---- the interface, on the dispatcher alone ----

class Reverse:
    """Test policy: latest request first, work-conserving."""
    name = "reverse"

    def recommend(self, group, waiting, now):
        return Recommendation(tuple(w.request_id for w in sorted(waiting, key=lambda w: w.position, reverse=True)), False)


class OnlyLast:
    """Test policy: holds back everything except the latest request."""
    name = "only_last"

    def recommend(self, group, waiting, now):
        return Recommendation((max(waiting, key=lambda w: w.position).request_id,), False)


class Bad:
    name = "bad"

    def __init__(self, ids):
        self.ids = ids

    def recommend(self, group, waiting, now):
        return Recommendation(tuple(self.ids), False)


def test_built_in_policies_recommend_queue_order():
    views = [WaitingRequest("r2", "g", (5, 1), 5, 0, (), {}), WaitingRequest("r1", "g", (5, 0), 5, 0, (), {})]
    assert StrictFifo().recommend("g", views, 5) == Recommendation(("r1", "r2"), True)
    assert FeasibleFirst().recommend("g", views, 5) == Recommendation(("r1", "r2"), False)


def test_a_policy_object_decides_the_order_and_the_engine_decides_feasibility():
    gate = Gate({"x", "y"})
    d = Dispatcher({"g": Reverse()})
    d.submit("r1", "g", 0, gate.need("r1", "x"))
    d.submit("r2", "g", 0, gate.need("r2", "y"))
    d.submit("r3", "g", 0, gate.need("r3", "z"))  # z never free: the policy cannot make it start
    d.reconsider(0)
    assert gate.started == ["r2", "r1"]
    assert d.pending_ids() == ["r3"]
    # Overtakes are measured by queue position, whatever the policy: r2 started before the earlier r1; r3 was never
    # passed by a later request.
    assert d.overtaken() == {"r1": 1}


def test_requests_left_out_of_a_recommendation_are_held_back():
    gate = Gate({"x", "y"})
    d = Dispatcher({"g": OnlyLast()})
    d.submit("r1", "g", 0, gate.need("r1", "x"))
    d.submit("r2", "g", 0, gate.need("r2", "y"))
    d.reconsider(0)
    assert gate.started == ["r2", "r1"]  # r2 first; then r1 is the only (latest) one left
    gate2 = Gate({"x"})
    d2 = Dispatcher({"g": OnlyLast()})
    d2.submit("r1", "g", 0, gate2.need("r1", "x"))
    d2.submit("r2", "g", 0, gate2.need("r2", "y"))  # y busy: r1 is held although x is free
    d2.reconsider(0)
    assert gate2.started == [] and d2.waiting_reasons()["r1"][0].code == "POLICY_HOLD"


@pytest.mark.parametrize("ids", [["r1", "zz"], ["r1", "r1"]])
def test_an_invalid_recommendation_is_an_error(ids):
    d = Dispatcher({"g": Bad(ids)})
    d.submit("r1", "g", 0, lambda now: [])
    with pytest.raises(DispatcherError):
        d.reconsider(0)


def test_policies_receive_read_only_snapshots():
    seen = []

    class Peek:
        name = "peek"

        def recommend(self, group, waiting, now):
            seen.extend(waiting)
            return FeasibleFirst().recommend(group, waiting, now)

    d = Dispatcher({"g": Peek()})
    d.submit("r1", "g", 3, lambda now: [WaitReason("EQUIPMENT_BUSY", "x", "busy")], info={"truck": "T1"})
    d.reconsider(3)
    w = seen[0]
    assert (w.request_id, w.queued_at, w.info["truck"]) == ("r1", 3, "T1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        w.request_id = "x"
    with pytest.raises(TypeError):
        w.info["truck"] = "T2"


def test_unknown_policy_name_is_refused():
    with pytest.raises(DispatcherError):
        Dispatcher({"g": "batch"})


# ---- head-of-line blocking at parallel hoppers ----

def test_strict_global_fifo_keeps_a_later_truck_waiting_while_a_usable_hopper_is_idle():
    """H2 takes yellow maize only. A (yellow, tips 10 min) takes H1 07:00-07:10. W (white) can use only H1 and
    waits. Under strict global FIFO, B (yellow) waits behind W although H2 is idle. A's lot flows from H1
    07:10-07:19; W tips into H1 07:19-07:20; B then tips into H2 at 07:19. Nobody is overtaken."""
    r = run(TWO_INDEPENDENT, A_W_B, policy="strict_fifo", tip_overrides={"A": 10})
    assert table(r, "hopper_admitted", "total_waiting_min", "overtaken_by_later") == {
        "A": (hm("07:00"), 0, 0), "W": (hm("07:19"), 19, 0), "B": (hm("07:19"), 19, 0)}
    model = TruckFlowModel(load_site_config(copy.deepcopy(TWO_INDEPENDENT)), load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": a, "commodity": c, "tonnes": kg} for t, a, c, kg in A_W_B]}),
        FixedServiceTimes({"tip": 1}, {("A", "tip"): 10}), policy="strict_fifo")
    model.run(hm("07:05"))
    assert [x.code for x in model.waiting_reasons()["B/tip"]] == ["QUEUE_ORDER"]


def test_work_conserving_feasible_first_lets_the_later_truck_use_the_idle_hopper():
    r = run(TWO_INDEPENDENT, A_W_B, policy="feasible_first", tip_overrides={"A": 10})
    assert table(r, "hopper_admitted", "total_waiting_min", "overtaken_by_later") == {
        "A": (hm("07:00"), 0, 0), "W": (hm("07:19"), 19, 1), "B": (hm("07:00"), 0, 0)}


# ---- selection per site and per experiment ----

def with_policies(raw, queue_policies):
    out = copy.deepcopy(raw)
    out["queue_policies"] = queue_policies
    return out


def test_site_setting_argument_and_per_group_mapping_give_identical_decisions():
    by_arg = run(TWO_INDEPENDENT, A_W_B, policy="strict_fifo", tip_overrides={"A": 10})
    by_site = run(with_policies(TWO_INDEPENDENT, {"default": "strict_fifo"}), A_W_B, policy=None, tip_overrides={"A": 10})
    by_group = run(with_policies(TWO_INDEPENDENT, {"default": "feasible_first", "groups": {"tip": "strict_fifo"}}),
                   A_W_B, policy=None, tip_overrides={"A": 10})
    assert _decisions(by_arg) == _decisions(by_site) == _decisions(by_group)
    assert by_site.queue_policies["tip"] == "strict_fifo" and by_group.queue_policies["weigh"] == "feasible_first"


def test_explicit_argument_overrides_the_site_and_the_default_is_feasible_first():
    site_strict = with_policies(TWO_INDEPENDENT, {"default": "strict_fifo"})
    overridden = run(site_strict, A_W_B, policy="feasible_first", tip_overrides={"A": 10})
    default = run(TWO_INDEPENDENT, A_W_B, policy=None, tip_overrides={"A": 10})
    reference = run(TWO_INDEPENDENT, A_W_B, policy="feasible_first", tip_overrides={"A": 10})
    assert _decisions(overridden) == _decisions(default) == _decisions(reference)
    assert set(default.queue_policies.values()) == {"feasible_first"}


def test_site_policy_names_and_groups_are_validated():
    for bad in ({"default": "batch"}, {"groups": {"tipping": "strict_fifo"}}, {"groups": {"tip": "fifo"}}):
        with pytest.raises(ConfigSchemaError):
            load_site_config(with_policies(TWO_INDEPENDENT, bad))


def test_config_hash_unchanged_for_sites_without_the_new_setting():
    """Hashes of the golden configurations recorded before this step."""
    assert config_hash(load_site_config(copy.deepcopy(GOLDEN["site_a_valid"]["config"]))) == \
        "e214e4680b9a3789de055c9b195e6471574d782c08a2dc16fe221c561dd15aec"
    assert config_hash(load_site_config(copy.deepcopy(GOLDEN["site_b_valid"]["config"]))) == \
        "f8a22f2f35f4a5a5439d45ece26033782780ed9a705b32f7ca0b90269dc4a8db"


def test_experiments_select_policies_through_the_site_and_record_them():
    raw = copy.deepcopy(GOLDEN["site_a_valid"]["config"])
    raw["demand"]["load"]["daily"] = 0
    plain = run_experiment(load_site_config(raw), replications=2, base_seed=3)
    explicit = run_experiment(load_site_config(raw), replications=2, base_seed=3, policy="feasible_first")
    assert plain.summary == explicit.summary
    assert plain.metadata["policy"] == "feasible_first"
    assert plain.metadata["queue_policies"]["tip"] == "feasible_first" and plain.metadata["policy_source"] == "default"
    site = load_site_config(with_policies(raw, {"default": "feasible_first", "groups": {"tip": "strict_fifo"}}))
    from_site = run_experiment(site, replications=2, base_seed=3)
    assert from_site.metadata["policy_source"] == "site"
    assert from_site.metadata["queue_policies"]["tip"] == "strict_fifo"
    assert from_site.summary["unload.max_overtaken"].mean == 0  # no overtaking at the hopper under strict FIFO...
    overridden = run_experiment(site, replications=2, base_seed=3, policy="feasible_first")
    assert overridden.metadata["policy_source"] == "argument" and overridden.summary == plain.summary


# ---- reporting for the six domain decisions ----

def weighbridge_site(lanes=2):
    raw = copy.deepcopy(ONE_HOPPER)
    raw["equipment"].append({"id": "WB1", "type": "weighbridge", "name": "Weighbridge", "cap": lanes, "time": [1, 1, 1]})
    raw["sequences"] = {"unload": ["weigh_in", "tip"]}
    return raw


def run_weighing(rows, slow):
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": a, "commodity": c, "tonnes": 30} for t, a, c in rows]})
    return TruckFlowModel(load_site_config(weighbridge_site()), script,
                          FixedServiceTimes({"tip": 1, "weigh_in": 1}, {(slow, "weigh_in"): 5}),
                          policy="feasible_first").run()


def test_d1_gate_arrival_and_queue_entry_orders_are_both_recorded():
    """P/Q case (test_starvation_diagnostics): P arrived first but joined the hopper queue after Q and tipped first.
    Queue-stage count: Q overtaken once in the queue. Gate-arrival count (existing metric): not an overtake."""
    r = run_weighing([("Y0", "07:00", "YM"), ("P", "07:00", "YM"), ("Q", "07:01", "WM")], slow="P")
    m = r.truck_metrics
    assert [m[t].arrival_seq for t in ("Y0", "P", "Q")] == [0, 1, 2]
    assert m["Q"].queue_seq["tip"] < m["P"].queue_seq["tip"]
    assert (m["Q"].overtaken_in_queue, m["Q"].overtaken_by_later, m["Q"].hopper_admitted_ahead_by_later_arrivals) == (1, 0, 0)


def test_d1_gate_arrival_fairness_counts_later_arrivals_admitted_first_even_without_a_queue_overtake():
    """Y (yellow) arrives 07:00 and weighs 5 min (07:00-07:05); X (yellow) arrives 07:01, weighs 07:01-07:02 and
    tips 07:02-07:03, before Y has even joined the hopper queue. Y tips 07:05-07:06 (30 t space left).
    No queue overtake, but one later gate arrival was admitted to a hopper before Y."""
    r = run_weighing([("Y", "07:00", "YM"), ("X", "07:01", "YM")], slow="Y")
    y = r.truck_metrics["Y"]
    assert (y.hopper_admitted, r.truck_metrics["X"].hopper_admitted) == (hm("07:05"), hm("07:02"))
    assert (y.overtaken_in_queue, y.overtaken_by_later, y.hopper_admitted_ahead_by_later_arrivals) == (0, 0, 1)


def test_d2_overtakes_split_into_physically_feasible_and_infeasible():
    one = run(ONE_HOPPER, YW_Y).truck_metrics["W1"]  # Y2 took H1, which W1 can use
    assert (one.overtaken_by_later, one.overtaken_feasible, one.overtaken_infeasible) == (1, 1, 0)
    two = run(TWO_INDEPENDENT, A_W_B, tip_overrides={"A": 10}).truck_metrics["W"]  # B took H2, which W cannot use
    assert (two.overtaken_by_later, two.overtaken_feasible, two.overtaken_infeasible) == (1, 0, 1)


def test_d4_simultaneous_arrivals_keep_the_arrival_script_order():
    forward = run(ONE_HOPPER, YW_Y).truck_metrics
    backward = run(ONE_HOPPER, list(reversed(YW_Y))).truck_metrics
    assert [forward[t].arrival_seq for t in ("Y1", "W1", "Y2")] == [0, 1, 2]
    assert [backward[t].arrival_seq for t in ("Y2", "W1", "Y1")] == [0, 1, 2]
    assert backward["Y2"].hopper_admitted == hm("07:00")  # first in the script, first served


def test_d5_pre_opening_waiting_is_separated_and_total_waiting_is_unchanged():
    """test_fairness gate case: T1 arrives 06:50, waits at the gate until 07:00 (pre-opening), weighs 07:00-07:02
    and tips 07:02-07:03; T2 arrives 07:00 and waits 2 min for the weighbridge (operational)."""
    raw = copy.deepcopy(ONE_HOPPER)
    raw["equipment"].append({"id": "WB1", "type": "weighbridge", "name": "Weighbridge", "cap": 1, "time": [2, 2, 2]})
    raw["sequences"] = {"unload": ["weigh_in", "tip"]}
    script = load_arrival_script({"trucks": [
        {"id": "T1", "activity": "unload", "arrive": "06:50", "commodity": "YM", "tonnes": 30},
        {"id": "T2", "activity": "unload", "arrive": "07:00", "commodity": "YM", "tonnes": 30}]})
    r = TruckFlowModel(load_site_config(raw), script, FixedServiceTimes({"tip": 1, "weigh_in": 2}),
                       policy="feasible_first").run()
    assert table(r, "total_waiting_min", "pre_opening_wait_min", "operational_wait_min") == {
        "T1": (10, 10, 0), "T2": (2, 0, 2)}


def test_d6_unfinished_waits_are_right_censored_and_kept_apart():
    """Strict FIFO, plant stops 07:15 (test_starvation_diagnostics): Y1 completed with no wait; Y2 censored at
    15 min. The existing mixed yellow-maize mean (7.5) is unchanged."""
    raw = copy.deepcopy(ONE_HOPPER)
    raw["hours"] = {"open": 7, "close": 7.25}
    r = run(raw, YW_Y, policy="strict_fifo")
    assert (r.truck_metrics["Y2"].wait_censored, r.truck_metrics["Y1"].wait_censored) == (True, False)
    ym = r.fairness["unload"].by_commodity["YM"]
    assert ym.mean_total_wait_min == 7.5
    assert (ym.completed_mean_wait_min, ym.completed_median_wait_min, ym.completed_p95_wait_min,
            ym.completed_max_wait_min) == (0, 0, 0, 0)
    assert (ym.censored, ym.censored_mean_wait_min, ym.censored_max_wait_min) == (1, 15, 15)


def test_attempts_across_groups_follow_queue_position():
    """Requests of different groups are attempted in one sequence ordered by queue position (as before the policy
    interface): g0 (t=0, never startable), h1 (t=1), g2 (t=2). h1 must start before g2, although g2's group comes
    first."""
    gate = Gate({"b", "c"})
    d = Dispatcher({"g": "feasible_first", "h": "feasible_first"})
    d.submit("g0", "g", 0, gate.need("g0", "z"))
    d.submit("h1", "h", 1, gate.need("h1", "b"))
    d.submit("g2", "g", 2, gate.need("g2", "c"))
    d.reconsider(2)
    assert gate.started == ["h1", "g2"]


def test_the_engine_shows_policies_the_trucks_facts():
    """Every queue group gets a peeking work-conserving policy; the snapshot carries the truck facts."""
    seen = {}

    class Peek:
        name = "peek"

        def recommend(self, group, waiting, now):
            for w in waiting:
                seen.setdefault(w.request_id, dict(w.info))
            return FeasibleFirst().recommend(group, waiting, now)

    from silo_engine.sim.truck_flow import QUEUE_GROUP
    script = load_arrival_script({"trucks": [
        {"id": t, "activity": "unload", "arrive": a, "commodity": c, "tonnes": kg} for t, a, c, kg in YW_Y]})
    r = TruckFlowModel(load_site_config(copy.deepcopy(ONE_HOPPER)), script, FixedServiceTimes({"tip": 1}),
                       policy={g: Peek() for g in set(QUEUE_GROUP.values())}).run()
    assert seen["W1/tip"] == {"truck_id": "W1", "arrival_seq": 1, "activity": "unload", "commodity": "WM",
                              "grade": None, "step": "tip"}
    assert seen["Y2/tip"]["arrival_seq"] == 2
    assert r.queue_policies["tip"] == "peek" and r.policy_source == "argument"
    assert _decisions(r) == _decisions(run(ONE_HOPPER, YW_Y))  # a position-ordered work-conserving policy = feasible_first
