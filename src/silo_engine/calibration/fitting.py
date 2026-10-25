"""Fit service-time distributions to time-study observations (docs/ventersdorp/DATA_CALIBRATION_PLAN.md §3).

- Families: lognormal, gamma, Weibull, each by maximum likelihood. Fits are listed by AIC (lowest first) with the
  Kolmogorov-Smirnov distance and the Anderson-Darling statistic. Their p-values are not given: with parameters
  estimated from the same data they would be optimistic.
- About 30 observations per activity or stratum is a guideline, not a minimum (approved correction C2): smaller
  samples are fitted, with a note, and their uncertainty shows in the bootstrap intervals.
- `bootstrap` resamples the observations (seeded, reproducible), refits a family and gives 95% percentile intervals
  for its parameters, mean and 90th percentile.
- `as_distribution` returns a configuration `Distribution` (with provenance) for an equipment step.

This module does not read site data itself and keeps no records; observations are passed in by the caller.
"""
import math
from dataclasses import dataclass, field
from statistics import NormalDist

from ..sim.distributions import _lower_gamma_regularized, quantile
from ..sim.random_streams import Stream

FAMILIES = ("lognormal", "gamma", "weibull")
GUIDELINE_N = 30


def _digamma(x: float) -> float:
    r = 0.0
    while x < 6:
        r -= 1 / x
        x += 1
    f = 1 / (x * x)
    return r + math.log(x) - 0.5 / x - f * (1 / 12 - f * (1 / 120 - f * (1 / 252 - f * (1 / 240 - f / 132))))


def _trigamma(x: float) -> float:
    r = 0.0
    while x < 6:
        r += 1 / (x * x)
        x += 1
    f = 1 / (x * x)
    return r + 1 / x + f / 2 + f / x * (1 / 6 - f * (1 / 30 - f * (1 / 42 - f / 30)))


def _fit_lognormal(xs: list[float]) -> dict:
    logs = [math.log(x) for x in xs]
    mu = sum(logs) / len(logs)
    sigma = math.sqrt(sum((v - mu) ** 2 for v in logs) / len(logs))
    return {"mu": mu, "sigma": sigma}


def _fit_gamma(xs: list[float]) -> dict:
    mean = sum(xs) / len(xs)
    s = math.log(mean) - sum(math.log(x) for x in xs) / len(xs)
    k = (3 - s + math.sqrt((s - 3) ** 2 + 24 * s)) / (12 * s)
    for _ in range(100):
        step = (math.log(k) - _digamma(k) - s) / (1 / k - _trigamma(k))
        k = max(k - step, k / 10)
        if abs(step) < 1e-12 * k:
            break
    return {"shape": k, "scale": mean / k}


def _fit_weibull(xs: list[float]) -> dict:
    top = max(xs)
    ys = [x / top for x in xs]  # scaled for numerical stability
    mean_log = sum(math.log(y) for y in ys) / len(ys)

    def f(k: float) -> float:
        w = [y ** k for y in ys]
        return sum(wi * math.log(y) for wi, y in zip(w, ys)) / sum(w) - 1 / k - mean_log
    lo, hi = 1e-3, 1.0
    while f(hi) < 0:
        hi *= 2
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
        if hi - lo < 1e-13 * hi:
            break
    k = (lo + hi) / 2
    scale = top * (sum(y ** k for y in ys) / len(ys)) ** (1 / k)
    return {"shape": k, "scale": scale}


FITTERS = {"lognormal": _fit_lognormal, "gamma": _fit_gamma, "weibull": _fit_weibull}


def cdf(family: str, p: dict, x: float) -> float:
    if family == "lognormal":
        return NormalDist(p["mu"], p["sigma"]).cdf(math.log(x))
    if family == "gamma":
        return _lower_gamma_regularized(p["shape"], x / p["scale"])
    return 1 - math.exp(-((x / p["scale"]) ** p["shape"]))


def loglik(family: str, p: dict, xs: list[float]) -> float:
    if family == "lognormal":
        mu, s = p["mu"], p["sigma"]
        return sum(-math.log(x) - math.log(s) - 0.5 * math.log(2 * math.pi) - (math.log(x) - mu) ** 2 / (2 * s * s)
                   for x in xs)
    if family == "gamma":
        k, t = p["shape"], p["scale"]
        return sum((k - 1) * math.log(x) - x / t - k * math.log(t) - math.lgamma(k) for x in xs)
    k, lam = p["shape"], p["scale"]
    return sum(math.log(k) - k * math.log(lam) + (k - 1) * math.log(x) - (x / lam) ** k for x in xs)


def mean_of(family: str, p: dict) -> float:
    if family == "lognormal":
        return math.exp(p["mu"] + p["sigma"] ** 2 / 2)
    if family == "gamma":
        return p["shape"] * p["scale"]
    return p["scale"] * math.gamma(1 + 1 / p["shape"])


def _gof(family: str, p: dict, xs: list[float]) -> tuple[float, float]:
    ys = sorted(xs)
    n = len(ys)
    fs = [min(max(cdf(family, p, y), 1e-15), 1 - 1e-15) for y in ys]
    ks = max(max((i + 1) / n - f, f - i / n) for i, f in enumerate(fs))
    ad = -n - sum((2 * i + 1) * (math.log(fs[i]) + math.log(1 - fs[n - 1 - i])) for i in range(n)) / n
    return ks, ad


def _check(values) -> list[float]:
    xs = [float(v) for v in values]
    if not xs:
        raise ValueError("No observations to fit.")
    if min(xs) <= 0:
        raise ValueError("Observed times must be positive for lognormal, gamma and Weibull fits.")
    if len(set(xs)) < 2:
        raise ValueError("At least two different observed values are needed to fit a distribution.")
    return xs


@dataclass
class FitReport:
    n: int
    fits: list[dict]  # by AIC, lowest first: family, params, loglik, aic, ks, ad
    best: str
    notes: list[str] = field(default_factory=list)
    source: str | None = None

    def as_distribution(self, family: str | None = None) -> dict:
        f = next(x for x in self.fits if x["family"] == (family or self.best))
        prefix = f"{self.source}; " if self.source else ""
        return {"family": f["family"], "params": dict(f["params"]),
                "source": f"{prefix}n={self.n}; {f['family']} by maximum likelihood; AIC {f['aic']:.1f}"}


def fit(values, families=FAMILIES, source: str | None = None) -> FitReport:
    xs = _check(values)
    fits = []
    for fam in families:
        p = FITTERS[fam](xs)
        ll = loglik(fam, p, xs)
        ks, ad = _gof(fam, p, xs)
        fits.append({"family": fam, "params": p, "loglik": ll, "aic": 2 * len(p) - 2 * ll, "ks": ks, "ad": ad})
    fits.sort(key=lambda f: f["aic"])
    notes = []
    if len(xs) < GUIDELINE_N:
        notes.append(f"n = {len(xs)} is below the {GUIDELINE_N}-observation guideline; the fit is reported with its "
                     "(wider) bootstrap uncertainty.")
    if len(fits) > 1 and fits[1]["aic"] - fits[0]["aic"] < 2:
        notes.append(f"{fits[0]['family']} and {fits[1]['family']} fit about equally well (AIC difference < 2).")
    return FitReport(len(xs), fits, fits[0]["family"], notes, source)


def bootstrap(values, family: str, resamples: int = 1000, seed: int = 20261025) -> dict:
    """95% percentile intervals for the family's parameters, mean and 90th percentile (seeded resampling)."""
    xs = _check(values)
    n = len(xs)
    point = FITTERS[family](xs)

    def stats(p: dict) -> dict:
        return {**p, "mean": mean_of(family, p), "p90": quantile({"family": family, "params": p}, 0.9)}
    draws: dict[str, list[float]] = {}
    for b in range(resamples):
        stream = Stream(seed, "bootstrap", family, b)
        res = [xs[min(int(stream.uniform() * n), n - 1)] for _ in range(n)]
        if len(set(res)) < 2:
            continue
        for k, v in stats(FITTERS[family](res)).items():
            draws.setdefault(k, []).append(v)
    out = {}
    for k, est in stats(point).items():
        d = sorted(draws[k])
        out[k] = {"estimate": est, "low": d[int(0.025 * (len(d) - 1))], "high": d[int(0.975 * (len(d) - 1))]}
    return out
