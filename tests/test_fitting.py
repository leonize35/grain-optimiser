"""Distribution fitting for time-study data (checklist A11; DATA_CALIBRATION_PLAN §3). Synthetic samples only.

Samples are "stratified": the quantiles at u = (i - 0.5) / n of a known distribution, so the expected estimates are
known without random noise. 30 observations is a guideline, not a minimum (approved correction C2)."""
import math

import pytest

from silo_engine.calibration.fitting import bootstrap, fit
from silo_engine.config.schema import Distribution
from silo_engine.sim.distributions import problems, quantile


def sample(spec, n):
    return [quantile(spec, (i - 0.5) / n) for i in range(1, n + 1)]


LOGN = {"family": "lognormal", "params": {"mu": math.log(4), "sigma": 0.5}}
GAMMA = {"family": "gamma", "params": {"shape": 3, "scale": 2}}
WEIB = {"family": "weibull", "params": {"shape": 2.5, "scale": 6}}


def params(report, family):
    return next(f for f in report.fits if f["family"] == family)["params"]


def test_maximum_likelihood_recovers_known_parameters():
    p = params(fit(sample(LOGN, 400)), "lognormal")
    assert p["mu"] == pytest.approx(math.log(4), abs=1e-9) and p["sigma"] == pytest.approx(0.5, rel=0.02)
    g = params(fit(sample(GAMMA, 400)), "gamma")
    assert g["shape"] == pytest.approx(3, rel=0.05) and g["scale"] == pytest.approx(2, rel=0.05)
    w = params(fit(sample(WEIB, 400)), "weibull")
    assert w["shape"] == pytest.approx(2.5, rel=0.03) and w["scale"] == pytest.approx(6, rel=0.03)


@pytest.mark.parametrize("spec", [{"family": "lognormal", "params": {"mu": 1, "sigma": 0.8}},
                                  {"family": "weibull", "params": {"shape": 3, "scale": 5}}])
def test_aic_prefers_the_generating_family(spec):
    r = fit(sample(spec, 400))
    assert r.best == spec["family"]
    assert r.fits[0]["family"] == r.best  # fits are listed by AIC
    assert all(f["ks"] >= 0 and f["ad"] >= 0 for f in r.fits)


def test_small_samples_are_fitted_with_a_note_not_refused():
    r = fit(sample(LOGN, 12))
    assert r.n == 12 and len(r.fits) == 3
    assert any("below the 30-observation guideline" in n for n in r.notes)
    assert not any("guideline" in n for n in fit(sample(LOGN, 40)).notes)


def test_bootstrap_intervals_are_reproducible_and_reflect_sample_size():
    small, large = sample(LOGN, 12), sample(LOGN, 400)
    a = bootstrap(small, "lognormal", resamples=300, seed=7)
    assert a == bootstrap(small, "lognormal", resamples=300, seed=7)
    assert a["mean"]["low"] <= sum(small) / 12 <= a["mean"]["high"]
    b = bootstrap(large, "lognormal", resamples=300, seed=7)
    width = lambda x: (x["mean"]["high"] - x["mean"]["low"]) / x["mean"]["estimate"]  # noqa: E731
    assert width(a) > 3 * width(b)
    assert set(a) >= {"mean", "p90", "mu", "sigma"}


def test_the_chosen_fit_is_a_valid_configuration_distribution():
    r = fit(sample(GAMMA, 60), source="synthetic test sample")
    d = r.as_distribution("gamma")  # a named family (AIC need not pick gamma at n = 60)
    assert problems(d) == [] and d["source"].startswith("synthetic test sample; n=60; gamma")
    Distribution.model_validate(d)
    assert r.as_distribution()["family"] == r.best


@pytest.mark.parametrize("values", [[], [1, 2, 0], [3, -1, 4]])
def test_values_must_be_positive(values):
    with pytest.raises(ValueError):
        fit(values)
