"""Staffing levels against defined targets (docs/OPERATOR_STAFFING_DESIGN.md §11): run each worker count of one
operator pool over the same seeds (common random numbers) and find the smallest count that meets every target.

- The pool's count is set to the level in every shift window that has workers; windows and everything else stay.
- Targets (each optional): mean turnaround of completed trucks (max), completion rate (min), tonnes received (min)
  and overtime (max): the last departure after closing on the last day, which needs every admitted truck finished
  ("cleared"); a replication that did not clear fails the overtime target. Turnaround is always reported with the
  completion rate (docs/MEASUREMENT_FRAMEWORK.md, K1 with K2).
- Criterion "ci" (default) uses the conservative end of the 95% confidence interval over replications; "mean" uses
  the mean. A level with any stalled or invalid replication does not meet its targets; failed runs are counted,
  never left out (MEASUREMENT_FRAMEWORK §3).
- No monotonicity is assumed: every level is reported, and a larger level failing after a smaller one met the
  targets is flagged.
- Every level also reports worker busy minutes and utilisation, so turnaround, throughput, overtime and labour can be
  weighed against each other. The smallest level meeting the targets is one output, not the staffing objective
  (docs/ventersdorp/IMPLEMENTATION_CHECKLIST.md, correction C3).

This is a calculation on the configured inputs. With unverified pools, task requirements or times it is not a
staffing recommendation, and the result says so.
"""
from dataclasses import dataclass, field

from .. import VERSION
from ..config.schema import SiteConfig, config_hash
from ..inputs.generated import generate_arrivals
from ..sim.random_streams import derived_seed
from ..sim.service_times import StochasticServiceTimes
from ..sim.truck_flow import ModelError, TruckFlowModel, TruckFlowResult
from .runner import ci


@dataclass(frozen=True)
class StaffingTargets:
    activity: str = "unload"
    max_mean_turnaround_min: float | None = None  # completed trucks only
    min_completion_rate: float | None = None
    min_received_t: float | None = None
    max_overtime_min: float | None = None  # after closing on the last day; requires clearance


@dataclass
class LevelResult:
    workers: int
    config_hash: str
    statuses: list[str]  # per replication: ok, stalled, invalid
    values: dict[str, list[float | None]]  # per measure, per replication
    summary: dict[str, dict]  # per measure: n, mean, low, high (95% CI)
    meets: dict[str, bool]  # per configured target
    all_met: bool


@dataclass
class StaffingSearchResult:
    pool: str
    levels: list[LevelResult]
    minimum: int | None  # smallest level meeting every target, None if none does
    non_monotonic: bool
    metadata: dict = field(default_factory=dict)


def with_workers(site: SiteConfig, pool: str, workers: int) -> SiteConfig:
    """The site with `pool` at `workers` in every shift window that has workers (other windows stay at 0)."""
    raw = site.model_dump(by_alias=True)
    found = False
    for p in raw["operator_pools"]:
        if p["id"] == pool:
            found = True
            for w in p["schedule"]:
                if w["count"] > 0:
                    w["count"] = workers
    if not found:
        raise ModelError(f"Unknown operator pool {pool}.")
    return SiteConfig.model_validate(raw)


def _measures(result: TruckFlowResult, pool: str, activity: str) -> dict[str, float | None]:
    s = result.summary.get(activity)
    arrived = (s.completed + s.unfinished + s.turned_away) if s else 0
    day = result.clearance[-1] if result.clearance else None  # last day: admission cut-off, closing, final clearance
    use = (result.staffing.get("pools") or {}).get(pool, {})
    return {
        "mean_turnaround_min": s.mean_turnaround_min if s else None,
        "completion_rate": s.completed / arrived if arrived else None,
        "received_t": result.received_kg / 1000,
        "overtime_min": day["overtime_used_min"] if day and day["admitted"] else (0.0 if day else None),
        "cleared": 1.0 if day and day["cleared"] else 0.0,
        "worker_busy_min": use.get("busy_operator_minutes"),  # labour requirement, for balancing (correction C3)
        "worker_utilisation": use.get("utilisation"),
    }


def minimum_workforce(site: SiteConfig, pool: str, levels: list[int], targets: StaffingTargets,
                      replications: int = 10, base_seed: int = 20261025, days: int = 1, demand_factor: float = 1.0,
                      policy: str | dict[str, str] | None = None, staffing: str | None = None,
                      criterion: str = "ci", arrivals=None) -> StaffingSearchResult:
    """`arrivals(site, seed)` gives the trucks of one replication (default: generated from the site's demand)."""
    if criterion not in ("ci", "mean"):
        raise ValueError("criterion is 'ci' or 'mean'")
    seeds = [derived_seed(base_seed, "replication", i) for i in range(replications)]
    goals = {"mean_turnaround_min": ("max", targets.max_mean_turnaround_min),
             "completion_rate": ("min", targets.min_completion_rate),
             "received_t": ("min", targets.min_received_t),
             "overtime_min": ("max", targets.max_overtime_min)}
    goals = {k: v for k, v in goals.items() if v[1] is not None}
    out: list[LevelResult] = []
    assumptions: list[str] = []
    for n in sorted(set(levels)):
        s = with_workers(site, pool, n)
        statuses: list[str] = []
        values: dict[str, list[float | None]] = {}
        for seed in seeds:
            trucks = (arrivals(s, seed) if arrivals is not None
                      else generate_arrivals(s, seed, days=days, demand_factor=demand_factor))
            r = TruckFlowModel(s, trucks, StochasticServiceTimes(s, seed), policy=policy, days=days,
                               staffing=staffing).run()
            assumptions = assumptions or list(r.assumptions)
            statuses.append("stalled" if r.stall is not None else
                            "invalid" if r.violations or r.material_balance_kg != 0 else "ok")
            for k, v in _measures(r, pool, targets.activity).items():
                values.setdefault(k, []).append(v)
        summary = {}
        for k, vs in values.items():
            c = ci(vs)
            hw = c.half_width or 0.0
            summary[k] = {"n": c.n, "mean": c.mean,
                          "low": None if c.mean is None else c.mean - hw, "high": None if c.mean is None else c.mean + hw}
        meets = {}
        for k, (kind, goal) in goals.items():
            vs, sm = values[k], summary[k]
            if any(st != "ok" for st in statuses) or any(v is None for v in vs):
                meets[k] = False  # a failed replication, or a replication without a value (e.g. not cleared)
                continue
            x = sm["mean"] if criterion == "mean" else (sm["high"] if kind == "max" else sm["low"])
            meets[k] = x <= goal if kind == "max" else x >= goal
        out.append(LevelResult(n, config_hash(s), statuses, values, summary, meets, all(meets.values()) if meets else True))
    met = [lv.workers for lv in out if lv.all_met]
    minimum = met[0] if met else None
    non_monotonic = minimum is not None and any(not lv.all_met for lv in out if lv.workers > minimum)
    unverified = [p.id for p in site.operator_pools if not p.verified]
    metadata = {"engine_version": VERSION, "base_config_hash": config_hash(site), "seeds": seeds,
                "replications": replications, "days": days, "demand_factor": demand_factor, "policy": policy,
                "staffing_scenario": staffing, "criterion": criterion, "targets": dict(goals), "assumptions": assumptions,
                "unverified_pools": unverified,
                "status": ("calculation on unverified inputs; not a staffing recommendation" if unverified
                           else "calculation on the configured inputs; not validated against site observations")}
    return StaffingSearchResult(pool, out, minimum, non_monotonic, metadata)
