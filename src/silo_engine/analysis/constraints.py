"""TLS slice T2: constraint candidates (docs/TLS_ANALYSIS_DESIGN.md §3). Analysis only.

Reads the run's `wait_causes`: truck-minutes of waiting per clock hour and cause, where each cause is a chain
"ROOT<...<FIRST" (the first reason the truck had, traced back to its root: e.g. a truck waiting for the incoming
weighbridge, whose lanes hold trucks waiting for their grading result, which a grader is producing:
"IN_SERVICE:G1#0<RELEASE:graded<BLOCKED:WB_IN"). Causes are summed by the resource at the root of each chain and
ranked. The leader is named the constraint only if it stands out: at least `lead_share` of all truck waiting and
at least `lead_ratio` times the next candidate (settings, provisional until calibrated; reported with the result).
Otherwise the verdict is "no single constraint". The leader is also reported per clock hour (hours with at least
`min_hour_min` truck-minutes of waiting), with the periods in which it stays the same.

This is evidence for a person to judge, not a proof: the tracing follows the reasons the engine records at each
moment (equal shares when a truck has several), and rates of a draining route are nominal.
"""
from ..config.schema import SiteConfig
from .resource_use import resource_use

CATEGORY = {"PLANT_CLOSED": "hours", "SYSTEM_CLOSED": "hours", "POLICY_HOLD": "policy", "QUEUE_ORDER": "policy",
            "LABOUR_UNAVAILABLE": "labour", "AREA_FULL": "area", "PHYSICAL_QUEUE_ORDER": "area",
            "BIN_FULL": "storage", "STOCK_SHORT": "storage", "EQUIPMENT_DOWN": "equipment down",
            "NO_PHYSICAL_ROUTE": "route", "COMMODITY_LOCK": "route", "PIT_INCOMPATIBLE": "route",
            "MERGE_PATH_DIFFERS": "route", "CONDITION": "condition", "RELEASE": "condition",
            "GRADE_PENDING": "condition", "UNKNOWN": "unknown"}


def _root(key: str) -> tuple[str, str, str]:
    """(candidate id, code, rest of the chain) of a cause."""
    root, _, via = key.partition("<")
    code, _, res = root.partition(":")
    if not res:
        return code, code, via
    return res.split("#")[0].split(":")[0], code, via


def _kind(site: SiteConfig, cid: str, code: str) -> str:
    eq = {e.id: e for e in site.equipment}
    if cid in eq:
        t = eq[cid].type
        return "station" if t in ("sampler", "weighbridge", "station") else t
    if code in CATEGORY:
        return CATEGORY[code]
    return "resource"


def _reconciled(result) -> bool:
    """Independent check: truck waiting in the causes (kind "truck") equals the waiting in the truck step records
    (reaching a step to its start, and service end to leaving a station), both cut off at the horizon end."""
    end = result.outcomes["horizon_end"]
    ms = 0
    for rec in result.records:
        if rec.admitted is None:
            continue
        for s in rec.steps:
            started = s.started if s.started is not None else end
            ms += max(0, min(started, end) - min(s.entered, end))
            if s.finished is not None and s.unit is not None:
                left = s.left if s.left is not None else (end if rec.departed is None else s.finished)
                ms += max(0, min(left, end) - min(s.finished, end))
    causes = sum(v for cell in result.wait_causes.get("truck", {}).values() for v in cell.values())
    return abs(causes - ms / 60000) <= 1e-6 * max(1.0, causes)


def constraint_candidates(site: SiteConfig, result, lead_share: float = 0.4, lead_ratio: float = 1.5,
                          min_hour_min: float = 5) -> dict:
    """Candidates of one run."""
    use = resource_use(site, result)
    util = {k: v["utilisation"] for k, v in use["equipment"].items()}
    util.update({k: v["utilisation"] for k, v in use["segments"].items()})  # belts and elevators: grain flowing
    out = rank_wait_causes(site, [result.wait_causes], util, lead_share, lead_ratio, min_hour_min)
    return {**out, "reconciled": _reconciled(result)}


def rank_wait_causes(site: SiteConfig, causes: list[dict], utilisation: dict[str, float | None],
                     lead_share: float = 0.4, lead_ratio: float = 1.5, min_hour_min: float = 5) -> dict:
    """Candidates from the wait causes of one or more runs (several: pooled, as the mean truck-minutes per run)."""
    scale = 1 / len(causes) if causes else 1.0
    cands: dict[str, dict] = {}
    by_hour: dict[int, dict[str, float]] = {}
    for kind in ("truck", "in_service"):
        for wc in causes:
            for hour, cell in wc.get(kind, {}).items():
                for key, minutes in cell.items():
                    minutes *= scale
                    cid, code, via = _root(key)
                    c = cands.setdefault(cid, {"id": cid, "kind": _kind(site, cid, code), "truck_min": 0.0,
                                               "direct_min": 0.0, "in_service_min": 0.0, "via": {}, "codes": {}})
                    c["truck_min"] += minutes
                    if kind == "in_service":
                        c["in_service_min"] += minutes
                    c["codes"][code] = c["codes"].get(code, 0.0) + minutes
                    if via:
                        c["via"][via] = c["via"].get(via, 0.0) + minutes
                    else:
                        c["direct_min"] += minutes
                    h = by_hour.setdefault(int(hour), {})
                    h[cid] = h.get(cid, 0.0) + minutes
    total = sum(c["truck_min"] for c in cands.values())
    in_service = sum(c["in_service_min"] for c in cands.values())
    ranked = sorted(cands.values(), key=lambda c: (-c["truck_min"], c["id"]))
    for c in ranked:
        c["share"] = c["truck_min"] / total if total else None
        c["utilisation"] = utilisation.get(c["id"])
        for f in ("truck_min", "direct_min", "in_service_min"):
            c[f] = round(c[f], 6)
        c["via"] = {k: round(v, 6) for k, v in sorted(c["via"].items(), key=lambda kv: -kv[1])}
        c["codes"] = {k: round(v, 6) for k, v in c["codes"].items()}

    constraint, verdict = None, "No waiting was recorded." if not ranked else ""
    if ranked:
        top = ranked[0]
        nxt = ranked[1]["truck_min"] if len(ranked) > 1 else 0.0
        if top["share"] >= lead_share and (nxt == 0 or top["truck_min"] >= lead_ratio * nxt):
            constraint = top["id"]
            verdict = (f"{top['id']} accounts for {top['share']:.0%} of truck waiting"
                       + (f", {top['truck_min'] / nxt:.1f} times the next candidate." if nxt else "."))
        else:
            verdict = (f"There is no single constraint: the leader {top['id']} accounts for {top['share']:.0%} of truck "
                       f"waiting (needs {lead_share:.0%} and {lead_ratio:g} times the next).")

    hourly = []
    for hour in sorted(by_hour):
        cell = by_hour[hour]
        minutes = sum(cell.values())
        if minutes < min_hour_min:
            continue
        leader = min(cell, key=lambda k: (-cell[k], k))
        hourly.append({"day": hour // 24 + 1, "hour": hour % 24, "leader": leader, "truck_min": round(minutes, 6),
                       "leader_share": cell[leader] / minutes})
    shifts: list[dict] = []
    for h in hourly:
        label = f"day {h['day']} {h['hour']:02d}:00"
        end_hour = (h["day"] - 1) * 24 + h["hour"] + 1
        end = f"day {end_hour // 24 + 1} {end_hour % 24:02d}:00"
        if shifts and shifts[-1]["leader"] == h["leader"] and shifts[-1]["to"] == label:
            shifts[-1]["to"] = end
        else:
            shifts.append({"from": label, "to": end, "leader": h["leader"]})

    return {"total_truck_min": round(total, 6), "in_service_min": round(in_service, 6), "runs": len(causes),
            "candidates": ranked, "constraint": constraint, "verdict": verdict,
            "by_hour": hourly, "shifts": shifts,
            "settings": {"lead_share": lead_share, "lead_ratio": lead_ratio, "min_hour_min": min_hour_min},
            "limitations": [
                "Waits at the gate (before admission) are not included; see the resource use report.",
                "A truck with several reasons at once counts each equally.",
                "A draining pit is traced to the slowest part of its route at nominal rates; shared belts are not "
                "considered.",
                "Thresholds are provisional settings, not calibrated."]}
