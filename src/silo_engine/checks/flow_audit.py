"""Independent grain-flow audit (docs/MATERIAL_FLOW_AUDIT.md).

Rebuilds the grain flow of a finished run from its *records* only: the site configuration, the arrival list, the
truck records, transfers and loads, and the closing bins and pits. It checks them against the physical rules. It does
not use the engine's counters or internal state, so an engine bookkeeping error shows up as a disagreement here.

Checks:
- conservation: globally, per pit, per bin, and per lot (no lot moved more than it held);
- bins over time: capacity (stock + incoming reservations), no negative stock, stock available when a load started,
  one commodity at a time;
- shared segments over time: one commodity at a time, at most `max_concurrent_feeds` streams, merging streams share the
  rest of the route, and a route is released no earlier than its clear time after the last grain;
- order: a transfer starts only after its lot was tipped; each load belongs to a loading truck and moves its tonnes;
- completion: finished >= flow start >= start; released only after finishing;
- outages (docs/INTERRUPTED_TRANSFERS.md §5): no grain flows through equipment while it is unavailable (I-A), no
  route containing unavailable equipment is reserved during the outage (I-B), suspensions are well formed (I-C).

Conveyors and elevators hold no inventory in this model: grain still in transit is counted in its source pit until
the transfer ends (the same as the prototype).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from ..config.schema import SiteConfig
from ..domain.quantities import tonnes_to_kg
from ..inputs.scripted import ScriptedTruck
from ..sim.time import MS_PER_DAY, hm, m

INF = float("inf")


@dataclass
class FlowAudit:
    problems: list[str] = field(default_factory=list)
    in_transit: list[str] = field(default_factory=list)  # transfers or loads still running when the run ended
    checked: dict[str, int] = field(default_factory=dict)  # what was checked, for the report

    @property
    def ok(self) -> bool:
        return not self.problems


def audit_flow(site: SiteConfig, trucks: list[ScriptedTruck], result) -> FlowAudit:
    a = FlowAudit()
    eq = {e.id: e for e in site.equipment}
    truck = {t.id: t for t in trucks}
    records = {r.truck_id: r for r in result.records}

    # ---- lots: what entered each pit, and when ----
    lot_kg: dict[str, int] = {}
    lot_pit: dict[str, str] = {}
    lot_commodity: dict[str, str] = {}
    lot_tipped: dict[str, int] = {}
    pit_in: dict[str, int] = defaultdict(int)
    for e in site.equipment:
        if e.type == "hopper" and e.level0:
            lot = f"L0-{e.id}"
            lot_kg[lot], lot_pit[lot], lot_commodity[lot], lot_tipped[lot] = tonnes_to_kg(e.level0), e.id, e.level_commodity, -1
            pit_in[e.id] += lot_kg[lot]
    received = 0
    for rec in result.records:
        for s in rec.steps:
            if s.step == "tip" and s.finished is not None:
                t = truck[rec.truck_id]
                lot = f"L-{rec.truck_id}"
                lot_kg[lot], lot_pit[lot], lot_commodity[lot], lot_tipped[lot] = t.kg, s.unit, t.commodity, s.finished
                pit_in[s.unit] += t.kg
                received += t.kg

    transfers, loads = list(result.transfers), list(result.loads)
    done_t = [x for x in transfers if x.finished is not None]
    done_l = [x for x in loads if x.finished is not None]
    a.in_transit = [f"transfer {x.id}: {x.kg} kg {x.pit} -> {x.bin}" for x in transfers if x.finished is None] + \
                   [f"load {x.id}: {x.kg} kg {x.bin} -> {x.truck_id}" for x in loads if x.finished is None]

    # ---- per lot ----
    moved: dict[str, int] = defaultdict(int)
    for x in transfers:
        if x.lot_id not in lot_kg:
            a.problems.append(f"transfer {x.id} moves unknown lot {x.lot_id}")
            continue
        if lot_pit[x.lot_id] != x.pit or x.path[0] != x.pit or x.path[-1] != x.bin:
            a.problems.append(f"transfer {x.id}: route {x.path} does not run from {lot_pit[x.lot_id]} to {x.bin}")
        if x.started < lot_tipped[x.lot_id]:
            a.problems.append(f"transfer {x.id} started before lot {x.lot_id} was tipped")
        moved[x.lot_id] += x.kg
    for lot, kg in moved.items():
        if kg > lot_kg.get(lot, 0):
            a.problems.append(f"lot {lot}: {kg} kg moved out of {lot_kg[lot]} kg")

    # ---- per pit, per bin, global ----
    pit_out = defaultdict(int)
    for x in done_t:
        pit_out[x.pit] += x.kg
    for pid, closing in result.pits.items():
        if pit_in[pid] - pit_out[pid] != closing:
            a.problems.append(f"pit {pid}: {pit_in[pid]} kg in - {pit_out[pid]} kg out != {closing} kg left")
    opening_bins = {e.id: tonnes_to_kg(e.inv) if e.type == "bin" and e.inv else 0 for e in site.equipment if e.type == "bin"}
    bin_in, bin_out = defaultdict(int), defaultdict(int)
    for x in done_t:
        bin_in[x.bin] += x.kg
    for x in done_l:
        bin_out[x.bin] += x.kg
    for bid, (closing, _) in result.bins.items():
        if opening_bins[bid] + bin_in[bid] - bin_out[bid] != closing:
            a.problems.append(f"bin {bid}: {opening_bins[bid]} + {bin_in[bid]} - {bin_out[bid]} kg != {closing} kg")
    dispatched = sum(x.kg for x in done_l)
    opening = sum(opening_bins.values()) + sum(lot_kg[k] for k in lot_kg if k.startswith("L0-"))
    closing = sum(v[0] for v in result.bins.values()) + sum(result.pits.values())
    if opening + received - dispatched != closing:
        a.problems.append(f"global: {opening} + {received} - {dispatched} kg != {closing} kg closing")
    if received != result.received_kg or dispatched != result.dispatched_kg:
        a.problems.append(f"engine counters disagree: received {result.received_kg} (records {received}), "
                          f"dispatched {result.dispatched_kg} (records {dispatched})")

    # ---- loads belong to loading trucks ----
    for x in loads:
        rec, t = records.get(x.truck_id), truck.get(x.truck_id)
        if rec is None or t is None or rec.activity != "load":
            a.problems.append(f"load {x.id} belongs to no loading truck")
        elif x.kg != t.kg or x.path[0] != x.bin:
            a.problems.append(f"load {x.id}: {x.kg} kg from {x.path[0]} for a {t.kg} kg order from {x.bin}")

    # ---- completion order ----
    for x in [*transfers, *loads]:
        if x.flow_started < x.started or (x.finished is not None and x.finished < x.flow_started):
            a.problems.append(f"{x.id}: start {x.started}, flow {x.flow_started}, finish {x.finished} out of order")
        if x.released is not None and (x.finished is None or x.released < x.finished):
            a.problems.append(f"{x.id}: route released at {x.released} before the grain finished ({x.finished})")

    _audit_bins(a, site, opening_bins, transfers, loads, lot_commodity)
    _audit_outages(a, site, [*transfers, *loads])
    _audit_segments(a, eq, transfers, loads, lot_commodity, truck)
    a.checked = {"lots": len(lot_kg), "transfers": len(transfers), "loads": len(loads), "bins": len(opening_bins),
                 "pits": len(result.pits)}
    return a


def _audit_bins(a, site, opening_bins, transfers, loads, lot_commodity) -> None:
    """Replay each bin: at equal times completions come before starts (the engine releases before it reserves)."""
    events = defaultdict(list)  # bin -> (time, order, kind, kg, commodity, id)
    for x in transfers:
        events[x.bin].append((x.started, 1, "reserve_in", x.kg, lot_commodity.get(x.lot_id), x.id))
        if x.finished is not None:
            events[x.bin].append((x.finished, 0, "receive", x.kg, lot_commodity.get(x.lot_id), x.id))
    for x in loads:
        events[x.bin].append((x.started, 1, "commit_out", x.kg, None, x.id))
        if x.finished is not None:
            events[x.bin].append((x.finished, 0, "dispatch", x.kg, None, x.id))
    for e in site.equipment:
        if e.type != "bin":
            continue
        cap = tonnes_to_kg(e.cap_t) if e.cap_t else None
        stock, incoming, outgoing = opening_bins[e.id], 0, 0
        content = e.inv_commodity if stock else None
        for t, _, kind, kg, commodity, xid in sorted(events[e.id], key=lambda v: (v[0], v[1])):
            if kind == "reserve_in":
                if content is not None and commodity != content:
                    a.problems.append(f"bin {e.id}: {xid} brings {commodity} into a bin holding {content} at {t}")
                incoming += kg
                content = content or commodity
            elif kind == "receive":
                incoming -= kg
                stock += kg
            elif kind == "commit_out":
                if stock - outgoing < kg:
                    a.problems.append(f"bin {e.id}: {xid} committed {kg} kg with {stock - outgoing} kg available at {t}")
                outgoing += kg
            else:
                outgoing -= kg
                stock -= kg
                if stock == 0 and incoming == 0:
                    content = None
            if stock < 0:
                a.problems.append(f"bin {e.id}: negative stock {stock} kg at {t}")
            if cap is not None and stock + incoming > cap:
                a.problems.append(f"bin {e.id}: {stock} kg + {incoming} kg reserved exceeds {cap} kg at {t}")


def _audit_segments(a, eq, transfers, loads, lot_commodity, truck) -> None:
    """Every stream holds its route segments from start to release (or to the end of the run)."""
    streams = []
    for x in transfers:
        streams.append((x.id, x.path, lot_commodity.get(x.lot_id), x.started, x.released, x.finished))
    for x in loads:
        streams.append((x.id, x.path, truck[x.truck_id].commodity if x.truck_id in truck else None,
                        x.started, x.released, x.finished))
    by_segment = defaultdict(list)
    for sid, path, commodity, start, released, finished in streams:
        end = released if released is not None else INF
        for i, seg in enumerate(path[1:-1], start=1):
            by_segment[seg].append((start, end, sid, commodity, tuple(path[i:])))
        if finished is not None and released is not None:
            clear = max((m(Decimal(str(eq[s].clear_minutes))) for s in path[1:-1]), default=0)
            if released < finished + clear:
                a.problems.append(f"{sid}: route released {released - finished} ms after the last grain; "
                                  f"clear time is {clear} ms")
    for seg, spans in by_segment.items():
        limit = eq[seg].max_concurrent_feeds or 1
        points = sorted({s for s, *_ in spans})
        for t in points:
            active = [s for s in spans if s[0] <= t < s[1]]
            if len(active) > limit:
                a.problems.append(f"segment {seg}: {len(active)} streams at {t} (limit {limit}): {[s[2] for s in active]}")
            if len({s[3] for s in active}) > 1:
                a.problems.append(f"segment {seg}: commodities {sorted({str(s[3]) for s in active})} together at {t}")
            if len({s[4] for s in active}) > 1:
                a.problems.append(f"segment {seg}: streams with different onward routes together at {t}")


def _audit_outages(a, site, streams) -> None:
    windows = defaultdict(list)  # equipment -> [(start, end)]
    for o in site.outages:
        start = (o.day - 1) * MS_PER_DAY + hm(o.start)
        windows[o.equipment].append((start, INF if o.end is None else (o.day - 1) * MS_PER_DAY + hm(o.end)))
    for x in streams:
        stops = [tuple(i) for i in getattr(x, "interruptions", [])]
        # I-C: ordered, inside the stream's life, only the last one may be open.
        for k, (stop, restart) in enumerate(stops):
            if stop < x.started or (restart is not None and restart < stop) or (restart is None and k != len(stops) - 1):
                a.problems.append(f"{x.id}: malformed suspension {stop}-{restart}")
            if x.finished is not None and (restart is None or restart > x.finished):
                a.problems.append(f"{x.id}: finished at {x.finished} while suspended ({stop}-{restart})")
        # Flowing time = [flow start, finish) minus suspensions.
        flowing, t = [], x.flow_started
        for stop, restart in sorted(stops, key=lambda v: v[0]):
            if stop > t:
                flowing.append((t, stop))
            t = max(t, INF if restart is None else restart)
        end = INF if x.finished is None else x.finished
        if t < end:
            flowing.append((t, end))
        for seg in x.path[1:-1]:
            for w0, w1 in windows.get(seg, []):
                if any(f0 < w1 and w0 < f1 for f0, f1 in flowing):  # I-A
                    a.problems.append(f"{x.id}: grain flowed while {seg} was unavailable ({w0}-{w1})")
                if w0 <= x.started < w1:  # I-B
                    a.problems.append(f"{x.id}: route reserved at {x.started} through {seg}, unavailable {w0}-{w1}")
