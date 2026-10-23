"""Seeded random streams, stochastic service times and generated arrivals.

Hand-checkable where the maths allows (inverse-CDF values); statistical where it does not, with tolerances
chosen to match the prototype's own acceptance test for arrivals (test 6).
"""
import copy
import json
import math
from pathlib import Path

import pytest

from silo_engine.config import load_site_config
from silo_engine.config.rules_validation import validate_rules
from silo_engine.inputs.generated import generate_arrivals
from silo_engine.sim.random_streams import Stream, exponential, triangular
from silo_engine.sim.service_times import StochasticServiceTimes
from silo_engine.sim.time import MS_PER_DAY, hm, m

GOLDEN = {c["name"]: c for c in json.loads((Path(__file__).parent / "golden" / "validation_cases.json").read_text(encoding="utf-8"))["cases"]}


def site_a(**demand_changes):
    raw = copy.deepcopy(GOLDEN["site_a_valid"]["config"])  # prototype Site A (illustrative values)
    raw["demand"]["load"]["daily"] = 0  # loading is not built yet
    for act, changes in demand_changes.items():
        raw["demand"][act].update(changes)
    return raw


# ---------------- streams and distributions ----------------

def draws(stream, n=5):
    return [stream.uniform() for _ in range(n)]


def test_same_key_gives_the_same_sequence_and_different_keys_differ():
    reference = draws(Stream(42, "truck", "unload", 1, 7))
    assert draws(Stream(42, "truck", "unload", 1, 7)) == reference
    assert draws(Stream(42, "truck", "unload", 1, 8)) != reference
    assert draws(Stream(43, "truck", "unload", 1, 7)) != reference
    assert all(0 <= x < 1 for x in reference)


def test_triangular_inverse_cdf_by_hand():
    # [min 2, mode 4, max 10]: F(mode) = (4-2)/(10-2) = 0.25.
    assert triangular(0.0, 2, 4, 10) == 2
    assert triangular(0.25, 2, 4, 10) == pytest.approx(4)
    assert triangular(0.5, 2, 4, 10) == pytest.approx(10 - math.sqrt(0.5 * 8 * 6))  # 5.101...
    assert triangular(0.999999, 2, 4, 10) == pytest.approx(10, abs=0.01)
    assert triangular(0.3, 5, 5, 5) == 5  # degenerate: fixed value


def test_exponential_inverse_cdf_by_hand():
    # Rate 2 per minute: u = 1 - e^-1 gives exactly 0.5 min.
    assert exponential(1 - math.exp(-1), 2.0) == pytest.approx(0.5)


# ---------------- service times ----------------

def test_service_times_follow_each_items_triangular_times_and_stay_in_range():
    site = load_site_config(site_a())
    times = StochasticServiceTimes(site, seed=7)
    draws = [times.duration_ms(f"T{i}", "weigh_in", "WB1") for i in range(2000)]  # WB1 time [1.5, 2, 3] min
    assert min(draws) >= m("1.5") and max(draws) <= m(3)
    assert sum(draws) / len(draws) == pytest.approx((1.5 + 2 + 3) / 3 * 60_000, rel=0.02)  # mean 130 000 ms


def test_a_trucks_service_time_does_not_depend_on_the_layout_or_order_of_draws():
    site = load_site_config(site_a())
    one, two = StochasticServiceTimes(site, seed=7), StochasticServiceTimes(site, seed=7)
    two.duration_ms("T9", "tip", "H1")  # an extra draw for another truck first
    assert one.duration_ms("T1", "tip", "H1") == two.duration_ms("T1", "tip", "H1")
    assert one.duration_ms("T1", "tip", "H1") != one.duration_ms("T2", "tip", "H1")
    assert StochasticServiceTimes(site, seed=8).duration_ms("T1", "tip", "H1") != one.duration_ms("T1", "tip", "H1")


# ---------------- generated arrivals ----------------

def test_arrivals_reproduce_the_hourly_profile_and_daily_volume():
    """Port of prototype test 6: 200 trucks/day, 30 days: mean within ±12 of 200, every hour's share within
    2 points of the profile's share."""
    site = load_site_config(site_a(unload={"daily": 200}, weigh={"daily": 0}))
    raw_profile = site.demand.unload.profile
    counts = [0] * 24
    days = 0
    for seed in range(30):
        trucks = [t for t in generate_arrivals(site, seed=seed, days=1) if not t.backlog]
        days += 1
        for t in trucks:
            counts[t.arrive_ms // 3_600_000] += 1
    total = sum(counts)
    assert abs(total / days - 200) < 12
    open_hours = range(6, 18)
    weight = sum(raw_profile[h] for h in open_hours)
    assert max(abs(counts[h] / total - raw_profile[h] / weight) for h in open_hours) < 0.02
    assert all(counts[h] == 0 for h in range(24) if h not in open_hours)


def test_arrivals_are_reproducible_and_independent_of_the_plant_layout():
    site = load_site_config(site_a())
    bigger = site_a()
    bigger["equipment"].append({"id": "H3", "type": "hopper", "name": "Hopper 3", "capT": 60, "rate": 400,
                                "tip": [4, 6, 9], "commodities": ["YM", "WM"]})
    bigger["edges"].append(["H3", "C1"])
    a = generate_arrivals(site, seed=11, days=2)
    assert a == generate_arrivals(site, seed=11, days=2)
    assert a == generate_arrivals(load_site_config(bigger), seed=11, days=2)
    assert a != generate_arrivals(site, seed=12, days=2)
    assert any(t.arrive_ms >= MS_PER_DAY for t in a)  # day 2 arrivals exist


def test_demand_factor_scales_volume():
    site = load_site_config(site_a(unload={"daily": 100}, weigh={"daily": 0}))
    base = sum(len([t for t in generate_arrivals(site, seed=s) if not t.backlog]) for s in range(30)) / 30
    more = sum(len([t for t in generate_arrivals(site, seed=s, demand_factor=1.2) if not t.backlog]) for s in range(30)) / 30
    assert abs(base - 100) < 8 and abs(more - 120) < 8


def test_commodity_mix_and_payload_follow_the_demand():
    """Site A unloading mix: yellow 60 %, white 30 %, soybeans 10 %; payload triangular [24, 32.5, 38] t."""
    site = load_site_config(site_a(unload={"daily": 300}, weigh={"daily": 0}))
    trucks = [t for s in range(10) for t in generate_arrivals(site, seed=s) if t.activity == "unload"]
    share = {c: sum(1 for t in trucks if t.commodity == c) / len(trucks) for c in ("YM", "WM", "SB")}
    assert share["YM"] == pytest.approx(0.6, abs=0.03) and share["WM"] == pytest.approx(0.3, abs=0.03)
    kg = [t.kg for t in trucks]
    assert min(kg) >= 24_000 and max(kg) <= 38_000
    assert sum(kg) / len(kg) == pytest.approx((24 + 32.5 + 38) / 3 * 1000, rel=0.02)


def test_opening_backlog_trucks_arrive_at_opening():
    site = load_site_config(site_a())  # initial queue: 6 unloading trucks
    backlog = [t for t in generate_arrivals(site, seed=1) if t.backlog]
    assert len(backlog) == 6 and {t.arrive_ms for t in backlog} == {hm("06:00")}


def test_grades_are_drawn_from_the_grade_mix():
    raw = site_a(unload={"daily": 300, "mix": {"YM": 1}, "grade_mix": {"YM": {"1": 0.8, "2": 0.2}}}, weigh={"daily": 0})
    raw["commodities"][0]["grades"] = ["1", "2"]
    raw["grade_segregation"] = "none"
    trucks = [t for s in range(5) for t in generate_arrivals(load_site_config(raw), seed=s) if t.activity == "unload"]
    assert sum(1 for t in trucks if t.grade == "1") / len(trucks) == pytest.approx(0.8, abs=0.04)


def test_graded_commodity_without_a_grade_mix_is_a_configuration_error():
    raw = site_a(unload={"mix": {"YM": 1}})
    raw["commodities"][0]["grades"] = ["1", "2"]
    raw["grade_segregation"] = "none"
    msgs = [i.msg for i in validate_rules(load_site_config(raw)).errors]
    assert msgs == ["Unloading trucks bring Yellow maize, which has grades, but the demand has no grade mix for it."]
