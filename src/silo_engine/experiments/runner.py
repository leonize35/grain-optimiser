"""Multi-replication experiments (port of the prototype's runExperiment / summarize / paired).

- Replication i uses a seed derived from the base seed and i. Running two scenarios with the same base seed gives
  each replication the same trucks and the same per-truck service draws (common random numbers), so paired
  differences isolate the effect of the change.
- Every replication is checked. A run that stalled, broke a rule, or does not balance its grain is marked failed
  and left out of the summary (CLAUDE.md: reject results from runs with invariant violations); `failed` counts
  them and `values()` returns None in their place so paired comparisons stay aligned.
- Confidence intervals: 95 %, Student t (table for up to 31 values, 1.96 beyond), as in the prototype.
- Metadata records what a result depends on: engine version, configuration hash, base seed and seeds,
  replications, days, demand factor, dispatch policy and the run's assumptions (CLAUDE.md §9).
"""
import math
from dataclasses import dataclass, field

from .. import VERSION
from ..config.schema import SiteConfig, config_hash
from ..inputs.generated import generate_arrivals
from ..sim.random_streams import derived_seed
from ..sim.service_times import StochasticServiceTimes
from ..sim.truck_flow import TruckFlowModel, TruckFlowResult

T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
       2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]


def t_critical(n: int) -> float | None:
    """Two-sided 95 % Student t value for n observations (n - 1 degrees of freedom)."""
    if n < 2:
        return None
    return T95[n - 2] if n - 1 <= len(T95) else 1.96


@dataclass(frozen=True)
class Interval:
    n: int
    mean: float | None
    sd: float | None
    half_width: float | None  # None when fewer than 2 values

    @property
    def low(self) -> float | None:
        return None if self.half_width is None else self.mean - self.half_width

    @property
    def high(self) -> float | None:
        return None if self.half_width is None else self.mean + self.half_width


@dataclass(frozen=True)
class PairedDifference(Interval):
    significant: bool = False  # the 95 % interval of (b - a) excludes zero


def ci(values: list[float | None]) -> Interval:
    xs = [x for x in values if x is not None and math.isfinite(x)]
    n = len(xs)
    if n == 0:
        return Interval(0, None, None, None)
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    t = t_critical(n)
    return Interval(n, mean, sd, None if t is None else t * sd / math.sqrt(n))


def paired(a: list[float | None], b: list[float | None]) -> PairedDifference:
    """Per-replication differences b - a, using only replications where both have a value."""
    diffs = [y - x for x, y in zip(a, b) if x is not None and y is not None]
    c = ci(diffs)
    significant = c.half_width is not None and abs(c.mean) > c.half_width
    return PairedDifference(c.n, c.mean, c.sd, c.half_width, significant)


@dataclass
class Replication:
    index: int
    seed: int
    status: str  # ok, stalled, invalid
    kpis: dict[str, float | None]
    detail: str | None = None


@dataclass
class ExperimentResult:
    replications: list[Replication]
    summary: dict[str, Interval]  # over successful replications only
    failed: int
    metadata: dict = field(default_factory=dict)

    def values(self, kpi: str) -> list[float | None]:
        """One value per replication (None for failed ones), aligned for paired comparisons."""
        return [r.kpis.get(kpi) if r.status == "ok" else None for r in self.replications]


def kpis_of(result: TruckFlowResult) -> dict[str, float | None]:
    out: dict[str, float | None] = {"received_t": result.received_kg / 1000}
    for act, s in result.summary.items():
        out[f"{act}.completed"] = s.completed
        out[f"{act}.unfinished"] = s.unfinished
        out[f"{act}.turned_away"] = s.turned_away
        out[f"{act}.mean_turnaround_min"] = s.mean_turnaround_min
        out[f"{act}.median_turnaround_min"] = s.median_turnaround_min
        out[f"{act}.p90_turnaround_min"] = s.p90_turnaround_min
        out[f"{act}.max_turnaround_min"] = s.max_turnaround_min
        out[f"{act}.mean_turnaround_incl_unfinished_min"] = s.mean_turnaround_incl_unfinished_min
    return out


def run_experiment(site: SiteConfig, replications: int = 10, base_seed: int = 20261019, days: int = 1,
                   demand_factor: float = 1.0, policy: str = "feasible_first") -> ExperimentResult:
    reps: list[Replication] = []
    assumptions: list[str] = []
    for i in range(replications):
        seed = derived_seed(base_seed, "replication", i)
        trucks = generate_arrivals(site, seed, days=days, demand_factor=demand_factor)
        model = TruckFlowModel(site, trucks, StochasticServiceTimes(site, seed), policy=policy, days=days)
        result = model.run()
        assumptions = assumptions or result.assumptions
        if result.stall is not None:
            status, detail = "stalled", f"no progress possible from {result.stall.time} ms"
        elif result.violations or result.material_balance_kg != 0:
            status, detail = "invalid", f"{len(result.violations)} rule violations, balance {result.material_balance_kg} kg"
        else:
            status, detail = "ok", None
        reps.append(Replication(i, seed, status, kpis_of(result), detail))
    good = [r for r in reps if r.status == "ok"]
    summary = {k: ci([r.kpis[k] for r in good]) for k in (good[0].kpis if good else {})}
    metadata = {"engine_version": VERSION, "config_hash": config_hash(site), "base_seed": base_seed,
                "seeds": [r.seed for r in reps], "replications": replications, "days": days,
                "demand_factor": demand_factor, "policy": policy,
                "deadlock_prevention": site.deadlock_prevention, "assumptions": assumptions,
                "successful": len(good), "failed": len(reps) - len(good)}
    return ExperimentResult(reps, summary, len(reps) - len(good), metadata)
