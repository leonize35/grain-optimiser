"""Truck outcomes, time on site, weighbridge instants and daily clearance (docs/MEASUREMENT_FRAMEWORK.md §1, K2, K3,
K6, §4). Computed from the run's truck records after the run; nothing here changes the simulation.

- Every arrived truck has exactly one outcome: completed, unfinished_on_site (admitted, still there at the end),
  unfinished_at_gate (never admitted) or turned_away (with its reason).
- Time on site is counted from gate arrival to departure or send-away, cut off at the horizon end (the last day's
  hard stop, or the run's end if earlier). Unfinished trucks are censored (lower bounds). The sum over trucks equals
  the integral of trucks present over the horizon (K6); it is an occupancy measure, not an estimate of turnaround.
- Clearance per day: the trucks admitted that day, how many were still on site at closing, and the final clearance
  time (the last of them to depart). A day is cleared only when every truck it admitted completed; a truck turned
  away or still on site leaves it uncleared.
"""
from .time import MS_PER_MINUTE

STATUSES = ("completed", "unfinished_on_site", "unfinished_at_gate", "turned_away")


def _minutes(ms: int) -> float:
    return ms / MS_PER_MINUTE


def truck_outcomes(records, end: int) -> dict[str, dict]:
    out = {}
    for r in records:
        if r.departed is not None:
            status, leave = "completed", r.departed
        elif r.turned_away is not None:
            status, leave = "turned_away", r.turned_away_at
        else:
            status, leave = ("unfinished_on_site" if r.admitted is not None else "unfinished_at_gate"), None
        stop = min(leave if leave is not None else end, end)
        gate_stop = min(r.admitted if r.admitted is not None else stop, stop)
        steps = {s.step: s for s in r.steps}
        wi, wo = steps.get("weigh_in"), steps.get("weigh_out")
        out[r.truck_id] = {
            "activity": r.activity, "status": status, "reason": r.turned_away, "arrived": r.arrived,
            "admitted": r.admitted, "exit": leave,
            "time_on_site_min": _minutes(max(0, stop - r.arrived)),
            "gate_min": _minutes(max(0, gate_stop - r.arrived)),
            "censored": leave is None or leave > end,
            "weighbridge": {"weigh_in_start": wi.started if wi else None, "weigh_in_end": wi.finished if wi else None,
                            "weigh_out_start": wo.started if wo else None, "weigh_out_end": wo.finished if wo else None},
        }
    return out


def outcome_summary(trucks: dict[str, dict]) -> dict[str, dict]:
    out = {}
    for act in sorted({x["activity"] for x in trucks.values()}):
        xs = [x for x in trucks.values() if x["activity"] == act]
        counts = {s: sum(1 for x in xs if x["status"] == s) for s in STATUSES}
        counts["total"] = len(xs)
        away: dict[str, dict] = {}
        for reason in sorted({x["reason"] for x in xs if x["status"] == "turned_away"}):
            ts = [x["time_on_site_min"] for x in xs if x["status"] == "turned_away" and x["reason"] == reason]
            away[reason] = {"count": len(ts), "mean_time_on_site_min": sum(ts) / len(ts), "max_time_on_site_min": max(ts)}
        total = sum(x["time_on_site_min"] for x in xs)
        gate = sum(x["gate_min"] for x in xs)
        out[act] = {"counts": counts, "turned_away": away,
                    "occupancy": {"truck_minutes": total, "gate_minutes": gate, "site_minutes": total - gate,
                                  "mean_observed_time_on_site_min": total / len(xs) if xs else None}}
    return out


def clearance(records, windows: list[tuple[int, int, int]], closes: list[int]) -> list[dict]:
    """windows: per day (open, admission cut-off, hard stop); closes: per day closing time (all ms)."""
    out = []
    for d, ((opens, cutoff, stop), close) in enumerate(zip(windows, closes)):
        admitted = [r for r in records if r.admitted is not None and opens <= r.admitted < stop]
        held = [r for r in records if r.admitted is None and r.turned_away is None and opens <= r.arrived < stop]
        cleared = bool(admitted) and all(r.departed is not None for r in admitted)
        exits = [r.departed if r.departed is not None else r.turned_away_at for r in admitted]
        final = max(exits) if cleared else None
        out.append({
            "day": d + 1, "opens": opens, "admission_cutoff": cutoff, "close": close, "hard_stop": stop,
            "admitted": len(admitted), "last_admission": max((r.admitted for r in admitted), default=None),
            "on_site_at_close": sum(1 for r, e in zip(admitted, exits) if e is None or e > close),
            "final_clearance": final, "cleared": cleared or not admitted,
            "overtime_used_min": None if final is None else _minutes(max(0, final - close)),
            "after_hard_stop": final is not None and final > stop,
            "remaining": sorted(r.truck_id for r in admitted if r.departed is None),
            "held_at_gate": len(held),
        })
    return out


def restricted_mean_time_to_completion(outcomes: dict, tau_min: float, activity: str = "unload") -> dict:
    """RMST_C(tau) on the cohort with full follow-up (MEASUREMENT_FRAMEWORK K7): trucks that arrived at least tau
    before the horizon end. Each contributes min(time to completion, tau); a truck turned away or unfinished never
    completes and contributes tau. No censoring occurs before tau, so no Kaplan-Meier assumption is needed; late
    arrivals are outside the cohort (reported). Time origin: gate arrival. tau has no default (question Q-M4)."""
    if not tau_min > 0:
        raise ValueError("tau must be a positive number of minutes")
    tau = round(tau_min * MS_PER_MINUTE)
    end = outcomes["horizon_end"]
    xs = [x for x in outcomes["trucks"].values() if x["activity"] == activity]
    cohort = [x for x in xs if x["arrived"] <= end - tau]
    done = [x for x in cohort if x["status"] == "completed" and x["exit"] - x["arrived"] <= tau]
    away = [x for x in cohort if x["status"] == "turned_away" and x["exit"] - x["arrived"] <= tau]
    total = sum(x["exit"] - x["arrived"] if x in done else tau for x in cohort)
    n = len(cohort)
    return {"activity": activity, "tau_min": tau_min, "cohort": n, "outside_cohort": len(xs) - n,
            "rmst_min": _minutes(total) / n if n else None,
            "completed_within_tau": len(done) / n if n else None,
            "turned_away_within_tau": len(away) / n if n else None}
