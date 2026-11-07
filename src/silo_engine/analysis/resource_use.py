"""TLS slice T1: resource use report and Little's law check (docs/TLS_ANALYSIS_DESIGN.md §3, §4).

Computed from a finished run's records; nothing here changes the simulation. Works for any configured site: the
resources are whatever the site defines and the run used.

Definitions (minutes; every interval is cut off at the horizon end, the last day's hard stop or the run's end):
- Open time: per day, opening to the hard stop (closing + overtime), summed. Utilisation = busy time inside open
  time / (lanes x open time). Service that runs past the hard stop (completed, A7) is `busy_after_hours_min`.
- Stations and hoppers (truck steps): busy = service start to service end; blocked = service end until the truck
  left (it could not move on); queued = truck-minutes from reaching the step to its service start, counted at the
  equipment that served the truck. Trucks still waiting at the end are not attributed to equipment (no unit yet):
  they appear per step under `unserved`.
- Graders (samples, not truck steps): busy = reservation of a grader lane to its release (ledger); queued = from the
  end of the truck's sampling to the start of grading.
- Grain route segments (belts, elevators, ...): reserved = union of the intervals in which any transfer or load held
  the segment; flowing = union of the intervals in which grain moved (after changeover, excluding interruptions).
- Gate: truck-minutes waiting outside (before admission); the part belonging to trucks still outside at the end is
  censored (a lower bound).
- Labour pools and waiting areas: as the run reports them.

Little's law: over the window from the first arrival (or opening, if earlier) to the horizon end, L = time-average
trucks present (a sweep of arrival and exit instants), arrival rate = arrivals / window, W = mean time on site from
the run's outcomes (censored). The exact form L = rate x W must hold (independent computations of the same total);
a failure is a measurement problem. The steady-state reading uses completed trucks only; its gap against L shows
how much the edges of the run (trucks still present or held at the end) distort the mean turnaround. The tolerance
is a setting reported with the result.
"""
from collections import defaultdict

from ..config.schema import SiteConfig
from ..sim.ledger import LaneClaim
from ..sim.time import MS_PER_MINUTE

STATION_TYPES = ("sampler", "grader", "weighbridge", "station")
LIMITATIONS = [
    "Hopper busy time includes time a truck waits for pit space during partial tipping (not yet separated).",
    "Queued time is counted at the equipment that served the truck, not the equipment that caused the wait "
    "(constraint attribution is slice T2).",
    "Pit full and pit empty time is not reported yet.",
]


def _min(ms: float) -> float:
    return ms / MS_PER_MINUTE


def _union(intervals: list[tuple[int, int]]) -> int:
    total, cur_s, cur_e = 0, None, None
    for s, e in sorted(i for i in intervals if i[1] > i[0]):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    return total + (cur_e - cur_s if cur_e is not None else 0)


def _overlap(s: int, e: int, windows: list[tuple[int, int]]) -> int:
    return sum(max(0, min(e, b) - max(s, a)) for a, b in windows)


def resource_use(site: SiteConfig, result, little_tolerance: float = 0.1) -> dict:
    end = result.outcomes["horizon_end"]
    windows = [(d["opens"], min(d["hard_stop"], end)) for d in result.clearance]
    open_ms = sum(max(0, b - a) for a, b in windows)
    start = windows[0][0] if windows else 0
    eq = {e.id: e for e in site.equipment}

    def lanes(e) -> int:
        return int(e.cap or 0) if e.type in STATION_TYPES else 1

    use: dict[str, dict] = {}

    def entry(eid: str) -> dict:
        if eid not in use:
            e = eq[eid]
            kind = "station" if e.type in ("sampler", "weighbridge", "station") else e.type
            use[eid] = {"kind": kind, "type": e.type, "lanes": lanes(e), "busy_ms": 0, "busy_open_ms": 0,
                        "blocked_ms": 0, "queued_ms": 0, "served": 0}
        return use[eid]

    unserved: dict[str, float] = defaultdict(float)
    sample_done: dict[str, int] = {}
    for rec in result.records:
        for s in rec.steps:
            if s.step == "sample" and s.finished is not None:
                sample_done[rec.truck_id] = s.finished
            if s.unit is None or s.started is None:
                if s.started is None and s.step != "grade":
                    unserved[s.step] += _min(max(0, end - s.entered))
                continue
            eid = s.unit.split("#")[0]
            if eid not in eq:
                continue
            u = entry(eid)
            fin = min(s.finished if s.finished is not None else end, end)
            st = min(s.started, end)
            u["busy_ms"] += fin - st
            u["busy_open_ms"] += _overlap(st, fin, windows)
            u["queued_ms"] += max(0, st - min(s.entered, end))
            u["served"] += 1
            if s.finished is not None:
                left = s.left if s.left is not None else (end if rec.departed is None else s.finished)
                u["blocked_ms"] += max(0, min(left, end) - min(s.finished, end))

    # Graders: lane reservations held by samples ("S-<truck>/grade").
    held: dict[str, tuple[int, str]] = {}
    for x in result.ledger_log:
        lane = next((c.resource for c in x.claims if isinstance(c, LaneClaim)), None)
        if lane is None or not x.reservation_id.endswith("/grade"):
            continue
        eid = lane.split("#")[0]
        if eid not in eq or eq[eid].type != "grader":
            continue
        if x.op == "reserve":
            held[x.reservation_id] = (x.time, eid)
        elif x.reservation_id in held:
            t0, _ = held.pop(x.reservation_id)
            _grader(entry(eid), x.reservation_id, t0, x.time, end, windows, sample_done)
    for rid, (t0, eid) in held.items():  # still grading at the end
        _grader(entry(eid), rid, t0, end, end, windows, sample_done)

    equipment = {}
    for eid, u in use.items():
        cap = u["lanes"] * open_ms
        equipment[eid] = {
            "kind": u["kind"], "type": u["type"], "lanes": u["lanes"], "busy_min": _min(u["busy_ms"]),
            "busy_after_hours_min": _min(u["busy_ms"] - u["busy_open_ms"]),
            "utilisation": u["busy_open_ms"] / cap if cap else None, "blocked_min": _min(u["blocked_ms"]),
            "queued_truck_min": _min(u["queued_ms"]), "served": u["served"],
            "mean_queue": u["queued_ms"] / open_ms if open_ms else None}

    reserved: dict[str, list] = defaultdict(list)
    flowing: dict[str, list] = defaultdict(list)
    for x in list(result.transfers) + list(result.loads):
        r_end = min(x.released if x.released is not None else end, end)
        f_end = min(x.finished if x.finished is not None else end, end)
        cuts = [(a, min(b if b is not None else end, end)) for a, b in x.interruptions]
        for seg in x.path[1:-1]:
            reserved[seg].append((x.started, r_end))
            flowing[seg] += _subtract((x.flow_started, f_end), cuts)
    segments = {}
    for seg in reserved:
        busy = _union(flowing[seg])
        segments[seg] = {"type": eq[seg].type if seg in eq else None, "reserved_min": _min(_union(reserved[seg])),
                         "flowing_min": _min(busy), "utilisation": busy / open_ms if open_ms else None}

    trucks = result.outcomes["trucks"]
    gate_q = sum(t["gate_min"] for t in trucks.values())
    censored = sum(t["gate_min"] for t in trucks.values() if t["admitted"] is None and t["censored"])
    gate = {"queued_truck_min": gate_q, "censored_truck_min": censored,
            "held_at_end": sum(1 for t in trucks.values() if t["status"] == "unfinished_at_gate")}

    pools = (result.staffing or {}).get("pools", {})
    labour = {p: {"busy_operator_min": v["busy_operator_minutes"], "available_operator_min": v["available_operator_minutes"],
                  "utilisation": v["utilisation"], "verified": v["verified"]} for p, v in pools.items()}
    areas = {a: {"time_average": v["time_average"], "peak": v["peak"]} for a, v in result.area_occupancy.items()}

    return {"window": {"start": start, "end": end, "open_minutes": _min(open_ms)}, "equipment": equipment,
            "segments": segments, "gate": gate, "unserved": dict(unserved), "labour": labour, "areas": areas,
            "little": _little(result, end, little_tolerance), "limitations": list(LIMITATIONS)}


def _grader(u: dict, rid: str, t0: int, t1: int, end: int, windows, sample_done: dict) -> None:
    t1 = min(t1, end)
    u["busy_ms"] += t1 - t0
    u["busy_open_ms"] += _overlap(t0, t1, windows)
    truck = rid[2:-len("/grade")] if rid.startswith("S-") else None
    if truck in sample_done:
        u["queued_ms"] += max(0, t0 - sample_done[truck])
    u["served"] += 1


def _subtract(iv: tuple[int, int], cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out = [iv]
    for a, b in cuts:
        nxt = []
        for s, e in out:
            if b <= s or a >= e:
                nxt.append((s, e))
                continue
            if s < a:
                nxt.append((s, a))
            if b < e:
                nxt.append((b, e))
        out = nxt
    return out


def _little(result, end: int, tolerance: float) -> dict:
    trucks = result.outcomes["trucks"]
    if not trucks:
        return {"window_min": 0, "L": None, "arrival_rate_per_min": None, "W_min": None, "exact_ok": None,
                "W_completed_min": None, "steady_gap": None, "tolerance": tolerance, "steady_ok": None}
    opens = result.clearance[0]["opens"] if result.clearance else end
    w0 = min(min(r.arrived for r in result.records), opens)
    span = end - w0
    events = []
    for r in result.records:  # independent of the outcomes: from the truck records themselves
        leave = r.departed if r.departed is not None else r.turned_away_at
        events += [(min(r.arrived, end), 1), (min(leave if leave is not None else end, end), -1)]
    integral, present, last = 0, 0, None
    for t, d in sorted(events):
        if last is not None:
            integral += present * (t - last)
        present, last = present + d, t
    n = len(trucks)
    L = integral / span if span else None
    rate = n / _min(span) if span else None
    W = sum(t["time_on_site_min"] for t in trucks.values()) / n
    done = [t["time_on_site_min"] for t in trucks.values() if t["status"] == "completed"]
    Wc = sum(done) / len(done) if done else None
    exact = L is not None and abs(L - rate * W) <= 1e-9 * max(1.0, L)
    gap = (rate * Wc - L) / L if (L and Wc is not None) else None
    return {"window_min": _min(span), "L": L, "arrival_rate_per_min": rate, "W_min": W, "exact_ok": exact,
            "W_completed_min": Wc, "steady_gap": gap, "tolerance": tolerance,
            "steady_ok": None if gap is None else abs(gap) <= tolerance}
