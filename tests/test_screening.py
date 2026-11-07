"""TLS slice T5 (docs/TLS_ANALYSIS_DESIGN.md §5): screening experiment. Test inputs only.

Factors are user-chosen changes, each with two levels given as configuration overlays (the store's overlay
operations; an empty list is the base). Up to 4 factors: full factorial; 5 or 6: half fraction (the last factor's
level is the product of the others, resolution V / VI, so main effects are not aliased with two-factor
interactions); more are refused. Every design point runs the same replication seeds (common random numbers). A
main effect = mean response at the high level - mean at the low level, per seed, then a 95 % interval over seeds.
"""
import itertools

import pytest

from silo_engine.analysis.screening import design_matrix, screening


def fake_run(cfg, replications, base_seed):
    """Response m = 10 + 3 a - 2 b + seed noise (the same noise at every design point: common random numbers)."""
    return [{"m": 10 + 3 * cfg.get("a", 0) - 2 * cfg.get("b", 0) + (s * 7) % 5} for s in range(replications)]


def factor(name, path):
    return {"name": name, "low": [], "high": [{"op": "set", "path": path, "value": 1}]}


def test_full_factorial_main_effects():
    r = screening({}, [factor("A", "a"), factor("B", "b"), factor("C", "c")], responses=["m"], replications=4,
                  run_fn=fake_run)
    assert r["design"] == "full factorial" and len(r["points"]) == 8
    eff = {e["factor"]: e for e in r["effects"]["m"]}
    assert (eff["A"]["effect"], eff["B"]["effect"], eff["C"]["effect"]) == (3, -2, 0)
    assert (eff["A"]["low"], eff["A"]["high"], eff["A"]["clear"]) == (3, 3, True)  # CRN: no spread between seeds
    assert eff["C"]["clear"] is False
    assert [e["factor"] for e in r["effects"]["m"]] == ["A", "B", "C"]  # ranked by size


@pytest.mark.parametrize("k, runs", [(1, 2), (4, 16), (5, 16), (6, 32)])
def test_designs_are_balanced_and_orthogonal(k, runs):
    m = design_matrix(k)
    assert len(m) == runs and len(set(map(tuple, m))) == runs
    for j in range(k):
        assert sum(row[j] for row in m) == 0  # as many high (+1) as low (-1)
    for i, j in itertools.combinations(range(k), 2):
        assert sum(row[i] * row[j] for row in m) == 0


def test_half_fraction_estimates_main_effects():
    fs = [factor(n, n.lower()) for n in "ABDEF"]
    r = screening({}, fs, responses=["m"], replications=3, run_fn=fake_run)
    assert r["design"].startswith("half fraction") and len(r["points"]) == 16
    assert {e["factor"]: e["effect"] for e in r["effects"]["m"]} == {"A": 3, "B": -2, "D": 0, "E": 0, "F": 0}


def test_limits_and_names():
    with pytest.raises(ValueError, match="1 to 6 factors"):
        screening({}, [factor(str(i), f"x{i}") for i in range(7)], responses=["m"], run_fn=fake_run)
    with pytest.raises(ValueError, match="unique"):
        screening({}, [factor("A", "a"), factor("A", "b")], responses=["m"], run_fn=fake_run)


def test_with_the_engine_a_change_with_no_effect_gives_exactly_zero():
    """Real runs (a small partial-tipping site with generated demand). Renaming the hopper changes nothing, so with
    common random numbers its effect is exactly 0; halving the tipping-time changes the mean turnaround."""
    from test_load_classes import site
    base = site(payload=[20, 25, 30])
    fs = [{"name": "rename", "low": [], "high": [{"op": "update_equipment", "id": "H1", "fields": {"name": "Other"}}]},
          {"name": "fast tip", "low": [], "high": [{"op": "update_equipment", "id": "H1", "fields": {"tip": [5, 5, 5]}}]}]
    r = screening(base, fs, responses=["unload.mean_turnaround_min"], replications=2, base_seed=3)
    eff = {e["factor"]: e for e in r["effects"]["unload.mean_turnaround_min"]}
    assert eff["rename"]["effect"] == 0 and eff["fast tip"]["effect"] < 0
    assert r["same_arrivals"] is True
    assert r["metadata"]["replications"] == 2 and len(r["metadata"]["seeds"]) == 2


def test_a_factor_that_changes_demand_is_flagged():
    """A factor that changes the arrivals breaks common random numbers for that comparison: same_arrivals is False."""
    from test_load_classes import site
    fs = [{"name": "busier", "low": [], "high": [{"op": "set", "path": "demand.unload.daily", "value": 90}]}]
    r = screening(site(payload=[20, 25, 30]), fs, responses=["unload.completed"], replications=1, base_seed=3)
    assert r["same_arrivals"] is False
