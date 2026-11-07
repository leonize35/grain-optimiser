"""TLS slice T4: CTQs and capability (docs/TLS_ANALYSIS_DESIGN.md §5). Analysis only.

A CTQ (critical to quality) is set per silo or per study; there is no default target:
    {"measure": "turnaround" | "weighbridge_interval" | "hopper_wait", "usl": minutes, "lsl": minutes (optional),
     "activity": "unload" (default), "turned_away_is_defect": false (default)}
- turnaround: gate arrival to departure; weighbridge_interval: start of weigh-in to end of weigh-out; hopper_wait:
  reaching the tipping step to starting to tip.
- One opportunity per truck. A completed truck is a defect if its value is above the USL (or below the LSL).
- Unfinished trucks are censored at the horizon end: a defect if the value so far is already above the USL, else
  unknown (reported apart, not assessed). A truck that never reached the measure's start has no value.
- Turned-away trucks are reported apart; they are assessed (as defects) only if `turned_away_is_defect`.

Across replications: the defect share per replication, its mean and 95 % interval (Student t). Yield = 1 - defect
share; DPMO = defects per million opportunities (pooled).

Performance indices from the pooled completed values by percentiles (turnaround is skewed, so normal-theory indices
would mislead; long-run simulated data gives performance, Pp/Ppk, not short-term capability): Pp = (USL - LSL) /
(P99.865 - P0.135); Ppu = (USL - median) / (P99.865 - median); Ppl = (median - LSL) / (median - P0.135); Ppk the
smaller of those defined. Percentiles by linear interpolation. Below `min_n` completed values the extreme
percentiles are not reliable and the index is flagged. Censored trucks are not in the percentiles (so the indices
are optimistic when many trucks are unfinished). The sigma level is given only when asked: the standard normal
quantile of the yield, plus the chosen shift (the 1.5 convention is a choice, not a default).
"""
from statistics import NormalDist

from ..experiments.runner import ci
from ..sim.time import MS_PER_MINUTE

MEASURES = ("turnaround", "weighbridge_interval", "hopper_wait")


def _value(rec, end: int, measure: str) -> tuple[float | None, bool]:
    """(minutes, censored) for one truck; (None, False) when it has no value for the measure."""
    steps = {s.step: s for s in rec.steps}
    if measure == "turnaround":
        start, stop = rec.arrived, rec.departed
    elif measure == "weighbridge_interval":
        wi, wo = steps.get("weigh_in"), steps.get("weigh_out")
        start = wi.started if wi is not None else None
        stop = wo.finished if wo is not None else None
    else:
        tip = steps.get("tip")
        start = tip.entered if tip is not None else None
        stop = tip.started if tip is not None else None
    if start is None or start > end:
        return None, False
    if stop is None or stop > end:
        return (end - start) / MS_PER_MINUTE, True
    return (stop - start) / MS_PER_MINUTE, False


def _pct(xs: list[float], p: float) -> float:
    pos = p * (len(xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def capability(results: list, ctq: dict, min_n: int = 30, sigma_level: bool = False, shift: float = 0.0) -> dict:
    measure = ctq.get("measure")
    if measure not in MEASURES:
        raise ValueError(f"Unknown CTQ measure {measure!r}: use one of {', '.join(MEASURES)}.")
    usl, lsl = ctq.get("usl"), ctq.get("lsl")
    if usl is None:
        raise ValueError("A CTQ needs an upper limit (usl, minutes); there is no default target.")
    activity = ctq.get("activity", "unload")
    away_defect = bool(ctq.get("turned_away_is_defect", False))
    out_of_spec = lambda v: v > usl or (lsl is not None and v < lsl)  # noqa: E731

    totals = {"assessed": 0, "defects": 0, "unknown": 0, "turned_away": 0}
    completed: list[float] = []
    censored: list[float] = []
    shares: list[float | None] = []
    for result in results:
        end = result.outcomes["horizon_end"]
        a = d = 0
        for rec in result.records:
            if rec.activity != activity:
                continue
            if rec.turned_away is not None:
                totals["turned_away"] += 1
                if away_defect:
                    a, d = a + 1, d + 1
                continue
            v, cens = _value(rec, end, measure)
            if v is None:
                continue
            if cens:
                censored.append(v)
                if v > usl:
                    a, d = a + 1, d + 1
                else:
                    totals["unknown"] += 1
                continue
            completed.append(v)
            a += 1
            d += out_of_spec(v)
        totals["assessed"] += a
        totals["defects"] += d
        shares.append(d / a if a else None)

    share = totals["defects"] / totals["assessed"] if totals["assessed"] else None
    iv = ci(shares)
    xs = sorted(completed)
    pct = {"p0_135": _pct(xs, 0.00135), "p50": _pct(xs, 0.5), "p99_865": _pct(xs, 0.99865)} if xs else None
    pp = ppk = None
    if pct:
        upper = (usl - pct["p50"]) / (pct["p99_865"] - pct["p50"]) if pct["p99_865"] > pct["p50"] else None
        lower = ((pct["p50"] - lsl) / (pct["p50"] - pct["p0_135"])
                 if lsl is not None and pct["p50"] > pct["p0_135"] else None)
        defined = [x for x in (upper, lower) if x is not None]
        ppk = min(defined) if defined else None
        if lsl is not None and pct["p99_865"] > pct["p0_135"]:
            pp = (usl - lsl) / (pct["p99_865"] - pct["p0_135"])
    out = {**totals, "ctq": dict(ctq), "replications": len(results),
           "defect_share": share, "yield": None if share is None else 1 - share,
           "dpmo": None if share is None else round(share * 1_000_000, 6),
           "by_replication": shares, "defect_share_mean": iv.mean,
           "defect_share_low": iv.low if iv.low is not None else (iv.mean if iv.n == 1 else None),
           "defect_share_high": iv.high if iv.high is not None else (iv.mean if iv.n == 1 else None),
           "percentiles": pct, "pp": pp, "ppk": ppk, "completed_n": len(xs), "min_n": min_n,
           "index_reliable": len(xs) >= min_n,
           "values": {"completed": xs, "censored": sorted(censored)},
           "notes": ["Censored (unfinished) trucks are not in the percentiles; indices are optimistic when many "
                     "trucks are unfinished.", "Simulated performance, not validated against the site."]}
    if sigma_level:
        y = out["yield"]
        out["sigma_level"] = None if y is None or y in (0, 1) else NormalDist().inv_cdf(y) + shift
        out["shift"] = shift
    return out
