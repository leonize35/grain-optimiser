"""Fitted service-time distributions alongside triangular (checklist A7, DATA_CALIBRATION_PLAN G-C1).

Each draw is one inverse-CDF transform of the truck's own uniform number, so common random numbers are kept: changing
one step's distribution changes no other draw. Quantile values below are standard closed forms."""
import math

import pytest

from silo_engine.config import load_site_config
from silo_engine.sim.distributions import quantile
from silo_engine.sim.service_times import StochasticServiceTimes
from silo_engine.sim.time import MS_PER_MINUTE
from silo_engine.sim.truck_flow import ModelError, TruckFlowModel
from test_outcomes_clearance import RAW, TRUCKS, load_arrival_script


def q(spec, u):
    return quantile(spec, u)


@pytest.mark.parametrize("spec, u, expected", [
    ({"family": "fixed", "params": {"value": 3}}, 0.7, 3),
    ({"family": "triangular", "params": {"min": 1, "mode": 2, "max": 5}}, 0.25, 1 + math.sqrt(0.25 * 4 * 1)),
    ({"family": "lognormal", "params": {"mu": math.log(4), "sigma": 0.5}}, 0.5, 4),
    ({"family": "weibull", "params": {"shape": 2, "scale": 3}}, 0.5, 3 * math.log(2) ** 0.5),
    ({"family": "gamma", "params": {"shape": 1, "scale": 2}}, 0.5, 2 * math.log(2)),  # exponential
    ({"family": "gamma", "params": {"shape": 2, "scale": 1}}, 0.5, 1.6783469900166608),  # P(2, x) = 1 - e^-x (1 + x)
    ({"family": "empirical", "values": [5, 1, 3, 2]}, 0.0, 1),
    ({"family": "empirical", "values": [5, 1, 3, 2]}, 0.6, 3),
    ({"family": "empirical", "values": [5, 1, 3, 2]}, 0.99, 5),
    ({"family": "lognormal", "params": {"mu": 0, "sigma": 1}, "shift": 2}, 0.5, 3),
    ({"family": "weibull", "params": {"shape": 1, "scale": 10}, "max": 5}, 0.9, 5),  # capped
])
def test_quantiles(spec, u, expected):
    assert q(spec, u) == pytest.approx(expected, rel=1e-9)


def test_lognormal_quantiles_are_monotone_and_match_the_normal():
    spec = {"family": "lognormal", "params": {"mu": 1, "sigma": 0.4}}
    xs = [q(spec, u) for u in (0.025, 0.5, 0.975)]
    assert xs[0] < xs[1] < xs[2]
    assert xs[2] == pytest.approx(math.exp(1 + 0.4 * 1.959963984540054), rel=1e-9)


def site_with(dist):
    raw = {**RAW, "equipment": [dict(e) for e in RAW["equipment"]]}
    raw["equipment"][0]["distributions"] = {"weigh_in": dist}  # WB_IN
    return load_site_config(raw)


def test_a_distribution_replaces_only_its_own_step():
    base = load_site_config(RAW)
    fitted = site_with({"family": "lognormal", "params": {"mu": math.log(2), "sigma": 0.3}})
    a, b = StochasticServiceTimes(base, 11), StochasticServiceTimes(fitted, 11)
    assert a.duration_ms("T1", "tip", "H1") == b.duration_ms("T1", "tip", "H1")
    assert a.duration_ms("T1", "weigh_out", "WB_OUT") == b.duration_ms("T1", "weigh_out", "WB_OUT")
    d = b.duration_ms("T1", "weigh_in", "WB_IN")
    assert d == b.duration_ms("T1", "weigh_in", "WB_IN") and d != a.duration_ms("T1", "weigh_in", "WB_IN")
    from silo_engine.sim.random_streams import Stream
    u = Stream(11, "service", "T1", "weigh_in").uniform()  # the same uniform the triangular draw used
    assert d == round(quantile({"family": "lognormal", "params": {"mu": math.log(2), "sigma": 0.3}}, u) * MS_PER_MINUTE)


@pytest.mark.parametrize("dist, words", [
    ({"family": "lognormal", "params": {"mu": 1}}, "sigma"),
    ({"family": "gamma", "params": {"shape": 0, "scale": 1}}, "positive"),
    ({"family": "empirical", "values": []}, "at least one"),
    ({"family": "empirical", "values": [1, -2]}, "negative"),
    ({"family": "triangular", "params": {"min": 3, "mode": 2, "max": 4}}, "min <= mode <= max"),
])
def test_invalid_distributions_are_refused(dist, words):
    s = site_with(dist)
    script = load_arrival_script({"trucks": [{"id": "T1", "activity": "unload", "arrive": "07:00",
                                              "commodity": "YM", "tonnes": 30}]})
    with pytest.raises(ModelError) as err:
        TruckFlowModel(s, script, StochasticServiceTimes(s, 1)).run()
    assert words in str(err.value)


def test_a_distribution_for_a_step_the_equipment_does_not_do_is_refused():
    raw = {**RAW, "equipment": [dict(e) for e in RAW["equipment"]]}
    raw["equipment"][0]["distributions"] = {"tip": {"family": "fixed", "params": {"value": 1}}}
    s = load_site_config(raw)
    script = load_arrival_script({"trucks": [{"id": t, "activity": "unload", "arrive": a, "commodity": "YM",
                                              "tonnes": 30} for t, a in TRUCKS[:1]]})
    with pytest.raises(ModelError, match="does not do tip"):
        TruckFlowModel(s, script, StochasticServiceTimes(s, 1)).run()
