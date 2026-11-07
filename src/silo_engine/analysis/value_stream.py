"""TLS slice T3: value-stream map of one truck activity (docs/TLS_ANALYSIS_DESIGN.md §4). Analysis only.

The site classifies its own steps: `value_adding`, `necessary` (necessary non-value-adding) or `waste`. There is no
default; unclassified steps are reported as such and process cycle efficiency is then not given.

For completed trucks, each truck's time on site (gate arrival to departure) is split exactly into: waiting at the
gate; per step, moving to it (from leaving the previous place), waiting for it, its service and being held after it;
and the time from leaving the last place to departure. The parts are checked to add up for every truck (`adds_up`).
Service time counts towards the step's class; waiting and being held count as waiting; moving as moving. A step
whose service happens away from the truck (grading) has service 0; the truck's wait for the result is waiting.
Time a truck in service waits (for pit space while tipping in portions, or for workers) is taken out of its service
and counted as waiting (`mean_held_in_service_min`), from the run's `wait_causes`.

Takt time = open time / trucks of the activity that arrived. A step's cycle time = its mean service time / the lanes
of the equipment that served it (stations: their lanes; a hopper or load point: 1).

Waste view (all trucks, unfinished ones counted to the horizon end): waiting, moving, unfinished and turned-away
trucks, mean trucks on site (Little's L) and the mean time from tipping a lot to its grain reaching storage.
"""
from statistics import mean

from ..config.schema import SiteConfig
from ..sim.time import MS_PER_MINUTE
from .resource_use import STATION_TYPES, resource_use

CLASSES = ("value_adding", "necessary", "waste")
NOT_MODELLED = ["Over-processing and rework (e.g. re-sampling) are not modelled.",
                "Defects in the grain itself are not modelled; defects here are trucks not served."]


def _m(ms: float) -> float:
    return ms / MS_PER_MINUTE


def value_stream(site: SiteConfig, result, classification: dict[str, str], activity: str = "unload") -> dict:
    bad = sorted(k for k, v in classification.items() if v not in CLASSES)
    if bad:
        raise ValueError(f"Step class for {', '.join(bad)} must be value_adding, necessary or waste.")
    end = result.outcomes["horizon_end"]
    eq = {e.id: e for e in site.equipment}
    order = list(getattr(site.sequences, activity))
    recs = [r for r in result.records if r.activity == activity]
    done = [r for r in recs if r.departed is not None]
    for r in done:
        for s in r.steps:
            if s.step not in order:
                order.append(s.step)

    held_in_service: dict[tuple[str, str], float] = {}
    for cell in result.wait_causes.get("in_service_by_truck", {}).values():
        for k, v in cell.items():
            tid, _, step = k.partition("|")
            held_in_service[(tid, step)] = held_in_service.get((tid, step), 0.0) + v * MS_PER_MINUTE
    per: dict[str, dict[str, list]] = {s: {"wait": [], "service": [], "blocked": [], "move": [], "held": []}
                                       for s in order}
    units: dict[str, set[str]] = {s: set() for s in order}
    parts = {"value_adding": 0, "necessary": 0, "waste": 0, "unclassified": 0, "waiting": 0, "moving": 0}
    adds_up, lead, gate = True, [], []
    for r in done:
        cur = r.admitted if r.admitted is not None else r.arrived
        g = cur - r.arrived
        total = g
        parts["waiting"] += g
        for s in r.steps:
            started = s.started if s.started is not None else s.entered
            finished = s.finished if s.finished is not None else started
            left = s.left if s.left is not None else finished
            on_site = s.unit is not None
            move, wait = s.entered - cur, started - s.entered
            service = finished - started if on_site else 0
            if not on_site:  # result produced elsewhere: the truck waits for it
                wait, left = finished - s.entered, finished
            blocked = left - finished
            held = min(service, held_in_service.get((r.truck_id, s.step), 0.0))  # waiting during service
            service -= held
            p = per[s.step]
            for k, v in (("move", move), ("wait", wait), ("service", service), ("blocked", blocked), ("held", held)):
                p[k].append(v)
            if on_site:
                units[s.step].add(s.unit)
            parts[classification.get(s.step, "unclassified")] += service
            parts["waiting"] += wait + blocked + held
            parts["moving"] += move
            total += move + wait + service + blocked + held
            cur = left
        parts["moving"] += r.departed - cur
        total += r.departed - cur
        adds_up &= abs(total - (r.departed - r.arrived)) < 1e-6
        lead.append(r.departed - r.arrived)
        gate.append(g)

    n = len(done)
    use = resource_use(site, result)
    open_min = use["window"]["open_minutes"]
    takt = open_min / len(recs) if recs else None
    steps = []
    for s in order:
        p = per[s]
        lanes = sum(int(eq[u.split("#")[0]].cap or 0) if eq[u.split("#")[0]].type in STATION_TYPES else 1
                    for u in {u.split("#")[0] for u in units[s]} if u.split("#")[0] in eq)
        svc = _m(mean(p["service"])) if p["service"] else None
        cycle = svc / lanes if (svc is not None and lanes) else None
        steps.append({"step": s, "class": classification.get(s, "unclassified"), "trucks": len(p["service"]),
                      "mean_move_min": _m(mean(p["move"])) if p["move"] else None,
                      "mean_wait_min": _m(mean(p["wait"])) if p["wait"] else None,
                      "mean_service_min": svc,
                      "mean_blocked_min": _m(mean(p["blocked"])) if p["blocked"] else None,
                      "mean_held_in_service_min": _m(mean(p["held"])) if p["held"] else None,
                      "lanes": lanes, "cycle_min": cycle,
                      "slower_than_takt": None if (cycle is None or takt is None) else cycle > takt})
    breakdown = {k: _m(v) / n if n else 0 for k, v in parts.items()}
    lead_mean = _m(mean(lead)) if lead else None
    notes = []
    pce = None
    if any(s["class"] == "unclassified" and s["trucks"] for s in steps):
        notes.append("Some steps are unclassified, so process cycle efficiency is not given: classify every step "
                     "as value-adding, necessary or waste.")
    elif lead_mean:
        pce = breakdown["value_adding"] / lead_mean

    return {"activity": activity, "completed_trucks": n, "mean_gate_min": _m(mean(gate)) if gate else None,
            "mean_lead_time_min": lead_mean, "steps": steps, "breakdown_min": breakdown, "adds_up": adds_up,
            "process_cycle_efficiency": pce, "takt_min": takt, "open_minutes": open_min,
            "waste": _waste(result, recs, end, use), "notes": notes, "classification": dict(classification)}


def _waste(result, recs, end: int, use: dict) -> dict:
    waiting = moving = 0
    for r in recs:
        if r.admitted is None:
            continue
        cur = r.admitted
        for s in r.steps:
            moving += max(0, min(s.entered, end) - min(cur, end))
            started = s.started if s.started is not None else end
            waiting += max(0, min(started, end) - min(s.entered, end))
            if s.finished is not None and s.unit is not None:
                left = s.left if s.left is not None else (end if r.departed is None else s.finished)
                waiting += max(0, min(left, end) - min(s.finished, end))
                cur = left
            elif s.finished is not None:
                cur = s.finished
            else:
                cur = end
    trucks = result.outcomes["trucks"]
    ids = {r.truck_id for r in recs}
    gate = sum(t["gate_min"] for k, t in trucks.items() if k in ids)
    lots = [x for x in result.lots.values() if x.truck_id is not None and x.truck_id in ids and x.tipped_at is not None]
    to_store = [_m((x.stored_at if x.stored_at is not None else end) - x.tipped_at) for x in lots]
    return {"waiting_truck_min": _m(waiting) + gate, "moving_truck_min": _m(moving),
            "unfinished_trucks": sum(1 for k, t in trucks.items() if k in ids and t["status"].startswith("unfinished")),
            "turned_away_trucks": sum(1 for k, t in trucks.items() if k in ids and t["status"] == "turned_away"),
            "mean_trucks_on_site": use["little"]["L"],
            "mean_tipping_to_storage_min": mean(to_store) if to_store else None,
            "not_modelled": list(NOT_MODELLED)}
