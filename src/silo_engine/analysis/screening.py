"""TLS slice T5: screening experiment (docs/TLS_ANALYSIS_DESIGN.md §5). Runs the engine; changes no site.

Factors are user-chosen changes with two levels, each a list of overlay operations (store.apply_overlay; [] is the
base configuration): [{"name", "low": ops, "high": ops}]. The design is a two-level full factorial for up to 4
factors, or a half fraction for 5 or 6 (the last factor's level is the product of the others: I = AB...K,
resolution V or VI, so main effects are not aliased with two-factor interactions). More factors are refused: use
fewer, or screen in stages.

Every design point runs the same replication seeds (common random numbers). For each response and seed, the main
effect = mean response over the high-level points - mean over the low-level points; the reported effect is its
mean over seeds with a 95 % Student t interval ("clear" when the interval excludes zero). Seeds where any point has
no value (a failed run, or a measure absent) are left out and counted. Effects are ranked by size.

Responses are run measures (experiments.runner.kpis_of names); with a CTQ also `ctq.defect_share` (slice T4).
"""
import copy
import itertools

from ..config import load_site_config
from ..config.schema import config_hash
from ..experiments.runner import arrival_hash, ci, kpis_of
from ..inputs.generated import generate_arrivals
from ..sim.random_streams import derived_seed
from ..sim.service_times import StochasticServiceTimes
from ..sim.truck_flow import TruckFlowModel
from ..store import apply_overlay
from .. import VERSION
from .capability import capability


def design_matrix(k: int) -> list[list[int]]:
    """Rows of -1 (low) / +1 (high), one column per factor."""
    if not 1 <= k <= 6:
        raise ValueError("A screening experiment takes 1 to 6 factors.")
    if k <= 4:
        return [list(r) for r in itertools.product((-1, 1), repeat=k)]
    rows = []
    for r in itertools.product((-1, 1), repeat=k - 1):
        last = 1
        for x in r:
            last *= x
        rows.append([*r, last])
    return rows


def engine_run(config: dict, replications: int, base_seed: int, ctq: dict | None = None,
               policy: str | None = None) -> list[dict | None]:
    """One response dict per replication (None for a stalled or invalid run), seeds as experiments.run_experiment."""
    site = load_site_config(copy.deepcopy(config))
    out: list[dict | None] = []
    for i in range(replications):
        seed = derived_seed(base_seed, "replication", i)
        trucks = generate_arrivals(site, seed)
        result = TruckFlowModel(site, trucks, StochasticServiceTimes(site, seed), policy=policy).run()
        if result.stall is not None or result.violations or result.material_balance_kg != 0:
            out.append(None)
            continue
        k = kpis_of(result)
        k["_arrival_hash"] = arrival_hash(trucks)
        if ctq is not None:
            k["ctq.defect_share"] = capability([result], ctq)["defect_share"]
        out.append(k)
    return out


def screening(base: dict, factors: list[dict], responses: list[str], replications: int = 5,
              base_seed: int = 20261107, ctq: dict | None = None, run_fn=None) -> dict:
    names = [f["name"] for f in factors]
    if len(set(names)) != len(names):
        raise ValueError("Factor names must be unique.")
    matrix = design_matrix(len(factors))
    design = "full factorial" if len(factors) <= 4 else f"half fraction (I = {'*'.join(names)})"
    points = []
    for row in matrix:
        cfg = copy.deepcopy(base)
        for f, level in zip(factors, row):
            cfg = apply_overlay(cfg, f["high"] if level > 0 else f["low"])
        if run_fn is not None:
            reps = run_fn(cfg, replications, base_seed)
        else:
            reps = engine_run(cfg, replications, base_seed, ctq)
        points.append({"levels": dict(zip(names, ("high" if x > 0 else "low" for x in row))), "replications": reps,
                       "config_hash": config_hash(load_site_config(copy.deepcopy(cfg))) if run_fn is None else None})
    same = all(len({p["replications"][s].get("_arrival_hash") for p in points if p["replications"][s]}) <= 1
               for s in range(replications))  # per seed, every design point had the same arrivals
    effects: dict[str, list[dict]] = {}
    for resp in responses:
        rows = []
        for j, name in enumerate(names):
            per_seed, left_out = [], 0
            for s in range(replications):
                hi = [p["replications"][s] for p, row in zip(points, matrix) if row[j] > 0]
                lo = [p["replications"][s] for p, row in zip(points, matrix) if row[j] < 0]
                vals_hi = [r.get(resp) if r else None for r in hi]
                vals_lo = [r.get(resp) if r else None for r in lo]
                if any(v is None for v in vals_hi + vals_lo):
                    left_out += 1
                    continue
                per_seed.append(sum(vals_hi) / len(vals_hi) - sum(vals_lo) / len(vals_lo))
            iv = ci(per_seed)
            low = iv.low if iv.low is not None else iv.mean
            high = iv.high if iv.high is not None else iv.mean
            clear = iv.n >= 2 and low is not None and (low > 0 or high < 0)
            rows.append({"factor": name, "effect": iv.mean, "low": low, "high": high, "clear": clear,
                         "seeds": iv.n, "seeds_left_out": left_out})
        effects[resp] = sorted(rows, key=lambda e: -(abs(e["effect"]) if e["effect"] is not None else -1))
    for p in points:
        p["replications"] = [None if r is None else {k: v for k, v in r.items() if not k.startswith("_")}
                             for r in p["replications"]]
    return {"design": design, "factors": [{"name": f["name"], "low": f["low"], "high": f["high"]} for f in factors],
            "points": points, "effects": effects,
            "same_arrivals": same if run_fn is None else None,
            "metadata": {"engine_version": VERSION, "base_seed": base_seed, "replications": replications,
                         "seeds": [derived_seed(base_seed, "replication", i) for i in range(replications)],
                         "ctq": ctq, "responses": list(responses)},
            "notes": ["Main effects only; with a half fraction, two-factor interactions are aliased with "
                      "higher-order ones.", "Simulated effects, not validated against the site."]}
