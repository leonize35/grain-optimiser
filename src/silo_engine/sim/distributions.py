"""Service-time distributions as inverse CDFs of one uniform number (DATA_CALIBRATION_PLAN G-C1).

A draw is quantile(spec, u) with u from the truck's own stream, so common random numbers are kept. Minutes.

Families (parameters in minutes unless stated):
- fixed: value
- triangular: min, mode, max (the prototype formula, `random_streams.triangular`)
- lognormal: mu, sigma of the natural log of the minutes (sigma > 0)
- gamma: shape, scale (both > 0); quantile by bisection on the regularized incomplete gamma function
- weibull: shape, scale (both > 0)
- empirical: `values`, resampled with equal probability (the u-th order statistic)
Optional `shift` adds a fixed minimum (location); optional `max` caps the result.

The normal quantile is `statistics.NormalDist.inv_cdf` (Wichura's AS241, fixed in the standard library since
Python 3.8); the gamma function is written out here so it does not depend on other library versions.
"""
import math
from statistics import NormalDist

from .random_streams import triangular

FAMILIES = ("fixed", "triangular", "lognormal", "gamma", "weibull", "empirical")
_EPS = 1e-15


def _lower_gamma_regularized(a: float, x: float) -> float:
    """P(a, x), by the series (x < a + 1) or the continued fraction (Numerical Recipes 6.2)."""
    if x <= 0:
        return 0.0
    ln_front = -x + a * math.log(x) - math.lgamma(a)
    if x < a + 1:
        term = total = 1.0 / a
        n = a
        for _ in range(10_000):
            n += 1
            term *= x / n
            total += term
            if abs(term) < abs(total) * 1e-16:
                break
        return total * math.exp(ln_front)
    tiny = 1e-300
    b = x + 1 - a
    c = 1 / tiny
    d = 1 / b
    h = d
    for i in range(1, 10_000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = tiny if abs(d) < tiny else d
        c = b + an / c
        c = tiny if abs(c) < tiny else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-16:
            break
    return 1 - math.exp(ln_front) * h


def _gamma_quantile(u: float, shape: float, scale: float) -> float:
    hi = max(shape, 1.0)
    while _lower_gamma_regularized(shape, hi) < u:
        hi *= 2
    lo = 0.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if _lower_gamma_regularized(shape, mid) < u:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-15 * hi:
            break
    return scale * (lo + hi) / 2


def quantile(spec: dict, u: float) -> float:
    family, p = spec["family"], spec.get("params") or {}
    uu = min(max(u, _EPS), 1 - _EPS)
    if family == "fixed":
        x = p["value"]
    elif family == "triangular":
        x = triangular(u, p["min"], p["mode"], p["max"])
    elif family == "lognormal":
        x = math.exp(p["mu"] + p["sigma"] * NormalDist().inv_cdf(uu))
    elif family == "gamma":
        x = _gamma_quantile(uu, p["shape"], p["scale"])
    elif family == "weibull":
        x = p["scale"] * (-math.log(1 - uu)) ** (1 / p["shape"])
    elif family == "empirical":
        values = sorted(spec["values"])
        x = values[min(int(u * len(values)), len(values) - 1)]
    else:
        raise ValueError(f"Unknown distribution family {family}")
    x += spec.get("shift") or 0
    cap = spec.get("max")
    return min(x, cap) if cap is not None else x


def problems(spec: dict) -> list[str]:
    """What is wrong with a distribution specification (manager-readable), or nothing."""
    family, p = spec.get("family"), spec.get("params") or {}
    need = {"fixed": ("value",), "triangular": ("min", "mode", "max"), "lognormal": ("mu", "sigma"),
            "gamma": ("shape", "scale"), "weibull": ("shape", "scale"), "empirical": ()}
    if family not in need:
        return [f"unknown family {family}; use one of {', '.join(FAMILIES)}"]
    missing = [k for k in need[family] if k not in p]
    if missing:
        return [f"{family} needs {', '.join(missing)}"]
    out = []
    if family == "lognormal" and not p["sigma"] > 0:
        out.append("lognormal sigma must be positive")
    if family in ("gamma", "weibull") and not (p["shape"] > 0 and p["scale"] > 0):
        out.append(f"{family} shape and scale must be positive")
    if family == "triangular" and not 0 <= p["min"] <= p["mode"] <= p["max"]:
        out.append("triangular needs 0 <= min <= mode <= max")
    if family == "fixed" and p["value"] < 0:
        out.append("a fixed time cannot be negative")
    if family == "empirical":
        values = spec.get("values") or []
        if not values:
            out.append("empirical needs at least one observed value")
        elif min(values) < 0:
            out.append("empirical values cannot be negative")
    if (spec.get("shift") or 0) < 0:
        out.append("shift cannot be negative")
    if spec.get("max") is not None and spec["max"] <= 0:
        out.append("max must be positive")
    return out
