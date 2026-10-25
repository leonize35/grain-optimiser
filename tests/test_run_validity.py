"""Failed replications are reported, never silently dropped; arms are checked for identical arrivals
(docs/MEASUREMENT_FRAMEWORK.md §3; checklist A6)."""
import copy

import pytest

from silo_engine.config import load_site_config
from silo_engine.experiments.runner import ExperimentResult, Replication, compare, run_experiment
from test_unloading_labour import site as two_silo_site


def demand_site(bin_t=5000, daily=20):
    raw = two_silo_site(workers=2)
    del raw["unloading_labour"], raw["operator_pools"]  # no shift events: a blocked run is detected as a stall
    raw["demand"] = {"unload": {"daily": daily, "payload": [30, 30, 30], "mix": {"YM": 1}}}
    for e in raw["equipment"]:
        if e["type"] == "bin":
            e["capT"] = bin_t
    return load_site_config(raw)


def test_each_replication_records_its_arrivals():
    a = run_experiment(demand_site(), replications=2, base_seed=5)
    b = run_experiment(demand_site(), replications=2, base_seed=5)
    c = run_experiment(demand_site(), replications=2, base_seed=5, demand_factor=1.5)
    assert [r.arrival_hash for r in a.replications] == [r.arrival_hash for r in b.replications]
    assert [r.arrival_hash for r in a.replications] != [r.arrival_hash for r in c.replications]
    assert all(r.intended == r.arrived > 0 and r.failure_time is None for r in a.replications)


def test_a_stalled_replication_is_listed_with_its_lost_arrivals():
    """Bins of 30 t fill with the first lot in each silo; the next lot can never leave its pit, so the run stalls
    and later arrivals are cancelled. The failure is listed with its time and the trucks that never arrived."""
    exp = run_experiment(demand_site(bin_t=30), replications=2, base_seed=5)
    assert exp.failed == 2 and all(r.status == "stalled" for r in exp.replications)
    f = exp.metadata["failures"]
    assert [x["replication"] for x in f] == [0, 1]
    for x, r in zip(f, exp.replications):
        assert x["status"] == "stalled" and x["failure_time"] == r.failure_time is not None
        assert x["intended"] == r.intended and x["not_arrived"] == r.intended - r.arrived > 0
    assert exp.metadata["summary_scope"] == "successful replications only: 0 of 2"


def rep(i, status, value, h="h"):
    return Replication(i, i, status, {"k": value}, arrival_hash=f"{h}{i}", intended=10, arrived=10)


def result(*reps):
    return ExperimentResult(list(reps), {}, sum(r.status != "ok" for r in reps))


def test_compare_reports_excluded_pairs_and_unrankable_arms():
    """A: ok 10, stalled, ok 30. B: ok 12, ok 25, invalid. One complete pair (difference 2); pairs 1 and 2 are
    excluded with their reasons; neither arm can be ranked best because each has a failure."""
    a = result(rep(0, "ok", 10), rep(1, "stalled", None), rep(2, "ok", 30))
    b = result(rep(0, "ok", 12), rep(1, "ok", 25), rep(2, "invalid", None))
    c = compare(a, b, "k")
    assert (c.planned, c.used, c.difference.mean) == (3, 1, 2)
    assert c.excluded == [(1, "A stalled"), (2, "B invalid")]
    assert (c.failures_a, c.failures_b, c.rankable_a, c.rankable_b) == (1, 1, False, False)
    assert c.note == "conditional on both arms running: 1 of 3 pairs used"


def test_compare_refuses_arms_with_different_arrivals():
    a = result(rep(0, "ok", 10), rep(1, "ok", 20))
    b = result(rep(0, "ok", 11), rep(1, "ok", 21, h="other"))
    with pytest.raises(ValueError, match="different arrivals"):
        compare(a, b, "k")
    c = compare(a, b, "k", same_arrivals=False)  # e.g. a demand change: arrivals differ by design
    assert c.used == 2 and c.difference.mean == 1


def test_compare_with_no_failures_is_unconditional():
    a = result(rep(0, "ok", 10), rep(1, "ok", 20))
    b = result(rep(0, "ok", 13), rep(1, "ok", 23))
    c = compare(a, b, "k")
    assert (c.used, c.excluded, c.rankable_a, c.rankable_b, c.note) == (2, [], True, True, "all 2 pairs used")
    assert copy.deepcopy(c.difference.mean) == 3
