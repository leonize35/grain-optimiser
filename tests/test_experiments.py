"""Multi-replication experiments: confidence intervals, paired comparisons, failed replications, run metadata."""
import copy
import json
from pathlib import Path

import pytest

from silo_engine import VERSION
from silo_engine.config import config_hash, load_site_config
from silo_engine.experiments.runner import ci, paired, run_experiment

GOLDEN = {c["name"]: c for c in json.loads((Path(__file__).parent / "golden" / "validation_cases.json").read_text(encoding="utf-8"))["cases"]}


def site_a_raw():
    raw = copy.deepcopy(GOLDEN["site_a_valid"]["config"])
    raw["demand"]["load"]["daily"] = 0  # loading is not built yet
    return raw


def test_confidence_interval_by_hand():
    """[10, 12, 14, 16, 18]: mean 14, sample sd sqrt(10) = 3.162, t(4 df) = 2.776, half-width 2.776*3.162/sqrt(5)."""
    c = ci([10, 12, 14, 16, 18])
    assert c.n == 5 and c.mean == 14
    assert c.sd == pytest.approx(10 ** 0.5)
    assert c.half_width == pytest.approx(2.776 * 10 ** 0.5 / 5 ** 0.5)
    assert ci([5]).half_width is None


def test_paired_difference_by_hand():
    """Differences b - a per replication: [1, 2, 3]: mean 2, sd 1, t(2 df) = 4.303, half-width 4.303/sqrt(3) = 2.484.
    Significant if |mean| > half-width: 2 < 2.484, so not significant."""
    d = paired([10, 20, 30], [11, 22, 33])
    assert d.mean == 2 and d.half_width == pytest.approx(4.303 / 3 ** 0.5)
    assert d.significant is False


def test_experiment_is_reproducible_and_carries_run_metadata():
    site = load_site_config(site_a_raw())
    a = run_experiment(site, replications=3, base_seed=2026)
    b = run_experiment(site, replications=3, base_seed=2026)
    assert [r.kpis for r in a.replications] == [r.kpis for r in b.replications]
    meta = a.metadata
    assert meta["engine_version"] == VERSION and meta["config_hash"] == config_hash(site)
    assert meta["replications"] == 3 and meta["base_seed"] == 2026 and len(meta["seeds"]) == 3
    assert meta["seeds"] == [r.seed for r in a.replications]
    assert "unload.mean_turnaround_min" in a.summary and a.summary["unload.mean_turnaround_min"].n == 3
    assert all(r.status == "ok" for r in a.replications)


def test_replications_with_a_stall_are_excluded_and_counted():
    """Bins far too small: grain cannot leave the pits, the hoppers fill and trucks wait for pit space forever."""
    raw = site_a_raw()
    for e in raw["equipment"]:
        if e["type"] == "bin":
            e["capT"], e["inv"] = 40, 0
    result = run_experiment(load_site_config(raw), replications=2, base_seed=1)
    assert [r.status for r in result.replications] == ["stalled", "stalled"]
    assert result.failed == 2
    assert result.summary == {}


def test_three_arm_comparison_uses_common_random_numbers():
    """Baseline, +20 % demand, and +20 % demand with a third hopper on Pit conveyor 1.
    Every arm uses the same replication seeds; the two +20 % arms see exactly the same trucks, so the hopper's
    effect is the paired difference demand-only -> demand + hopper (not baseline -> demand + hopper).
    The sign of the hopper effect is NOT asserted: it depends on the dispatch policy (see PORT_LOG step 11, where
    under feasible-first the extra hopper raises changeovers on the shared elevator)."""
    from silo_engine.inputs.generated import generate_arrivals
    base = load_site_config(site_a_raw())
    plus_raw = site_a_raw()
    plus_raw["equipment"].append({"id": "H3", "type": "hopper", "name": "Hopper 3", "capT": 60, "rate": 400,
                                  "tip": [4, 6, 9], "commodities": ["YM", "WM"]})
    plus_raw["edges"].append(["H3", "C1"])
    plus = load_site_config(plus_raw)
    kpi = "unload.mean_turnaround_incl_unfinished_min"
    arms = {"baseline": run_experiment(base, replications=5, base_seed=7),
            "demand": run_experiment(base, replications=5, base_seed=7, demand_factor=1.2),
            "demand_hopper": run_experiment(plus, replications=5, base_seed=7, demand_factor=1.2)}
    assert all(a.failed == 0 for a in arms.values())
    assert arms["baseline"].metadata["seeds"] == arms["demand"].metadata["seeds"] == arms["demand_hopper"].metadata["seeds"]
    for seed in arms["demand"].metadata["seeds"]:
        assert generate_arrivals(base, seed, demand_factor=1.2) == generate_arrivals(plus, seed, demand_factor=1.2)
    growth = paired(arms["baseline"].values(kpi), arms["demand"].values(kpi))
    hopper = paired(arms["demand"].values(kpi), arms["demand_hopper"].values(kpi))
    assert growth.n == 5 and growth.mean > 0  # more trucks, longer turnaround
    assert hopper.n == 5 and hopper.half_width is not None
    assert arms["demand_hopper"].metadata["demand_factor"] == 1.2
