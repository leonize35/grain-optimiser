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
  route containing unavailable equipment is reserved during the outage (I-B), suspensions are well formed (I-C);
- stock (docs/STOCK_ADJUSTMENTS.md): physical equations include process losses, which may take only uncommitted
  stock; the book is rebuilt from its postings; the reconciliation's components are rebuilt and the unexplained part
  must be 0; observations must match the replayed physical and book stock at their time. Book corrections and
  observations do not appear in the physical equations, so one that changed physical stock shows as a bin imbalance;
- truck access (docs/SAMPLER_ACCESS_DESIGN.md): a truck that needs no sampling receives no sampling or grading; no
  two trucks occupy one station bay at the same time; co-located sampling never uses more sampling units than
  exist; trucks leave a single-file area in the order they entered it, except through a declared bypass.

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
    losses = list(getattr(result, "losses", []))
    bin_lost = defaultdict(int)
    for x in losses:
        bin_lost[x.bin] += x.kg
    for bid, (closing, _) in result.bins.items():
        if opening_bins[bid] + bin_in[bid] - bin_out[bid] - bin_lost[bid] != closing:
            a.problems.append(f"bin {bid}: {opening_bins[bid]} + {bin_in[bid]} - {bin_out[bid]} - {bin_lost[bid]} lost "
                              f"kg != {closing} kg")
    dispatched = sum(x.kg for x in done_l)
    lost = sum(bin_lost.values())
    opening = sum(opening_bins.values()) + sum(lot_kg[k] for k in lot_kg if k.startswith("L0-"))
    closing = sum(v[0] for v in result.bins.values()) + sum(result.pits.values())
    if opening + received - dispatched - lost != closing:
        a.problems.append(f"global: {opening} + {received} - {dispatched} - {lost} lost kg != {closing} kg closing")
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

    _audit_bins(a, site, opening_bins, transfers, loads, lot_commodity, losses)
    if hasattr(result, "book"):
        _audit_stock(a, site, opening_bins, done_t, done_l, losses, result)
    _audit_outages(a, site, [*transfers, *loads])
    _audit_access(a, site, trucks, result)
    _audit_segments(a, eq, transfers, loads, lot_commodity, truck)
    a.checked = {"lots": len(lot_kg), "transfers": len(transfers), "loads": len(loads), "bins": len(opening_bins),
                 "pits": len(result.pits)}
    return a


def _audit_bins(a, site, opening_bins, transfers, loads, lot_commodity, losses=()) -> None:
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
    for x in losses:  # stock events run after completions and before new reservations at the same instant
        events[x.bin].append((x.time, 0.5, "loss", x.kg, None, x.id))
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
            elif kind == "loss":
                if stock - outgoing < kg:
                    a.problems.append(f"bin {e.id}: loss {xid} of {kg} kg took committed stock "
                                      f"({stock - outgoing} kg uncommitted) at {t}")
                stock -= kg
                if stock == 0 and incoming == 0:
                    content = None
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


def _audit_stock(a, site, opening_bins, done_t, done_l, losses, result) -> None:
    """Rebuild book and physical stock per bin over time from the records; check the book, the observations and the
    reconciliation (docs/STOCK_ADJUSTMENTS.md §4)."""
    book0 = {o.bin: tonnes_to_kg(o.tonnes) if o.tonnes else 0 for o in site.opening_book}
    book = {b: book0.get(b, kg) for b, kg in opening_bins.items()}
    phys = dict(opening_bins)
    comps = {b: {"administrative": 0, "survey_based": 0, "unposted_loss": 0} for b in opening_bins}
    timeline = [(x.finished, 0, "receive", x) for x in done_t] + [(x.finished, 0, "dispatch", x) for x in done_l]
    loss_by_id = {x.id: x for x in losses}
    timeline += [(e.time, 1 + i, "stock", e) for i, e in enumerate(result.stock_log)]
    observations = {o.id: o for o in result.observations}
    seen_obs: dict[str, int] = {}
    for _, _, kind, x in sorted(timeline, key=lambda v: (v[0], v[1])):
        if kind == "receive":
            book[x.bin] += x.kg
            phys[x.bin] += x.kg
        elif kind == "dispatch":
            book[x.bin] -= x.kg
            phys[x.bin] -= x.kg
        elif not x.applied:
            if x.delta_physical_kg or x.delta_book_kg:
                a.problems.append(f"refused stock event {x.id} changed stock")
        elif x.kind == "process_loss":
            lr = loss_by_id.get(x.id)
            if lr is None:
                a.problems.append(f"stock event {x.id}: applied loss missing from the loss records")
                continue
            phys[x.bin] -= lr.kg
            if lr.posted:
                book[x.bin] -= lr.kg
            else:
                comps[x.bin]["unposted_loss"] += lr.kg
        elif x.kind == "stock_measurement":
            o = observations.get(x.id)
            if o is None or (o.physical_kg, o.book_kg) != (phys[x.bin], book[x.bin]) or \
                    o.minus_book_kg != o.observed_kg - book[x.bin] or o.minus_physical_kg != o.observed_kg - phys[x.bin]:
                a.problems.append(f"observation {x.id}: records give physical {phys[x.bin]} kg and book {book[x.bin]} kg "
                                  f"at {x.time}; result says {o}")
            if o is not None:
                seen_obs[x.id] = o.observed_kg
        else:  # book correction: never a physical change
            if x.delta_physical_kg:
                a.problems.append(f"book correction {x.id} changed physical stock")
            book[x.bin] += x.delta_book_kg
            comps[x.bin]["administrative" if x.basis == "administrative" else "survey_based"] += x.delta_book_kg
    for b in opening_bins:
        if book[b] != result.book.get(b):
            a.problems.append(f"book {b}: records give {book[b]} kg, result says {result.book.get(b)} kg")
        closing = result.bins[b][0]
        d = book[b] - closing
        opening_diff = book0.get(b, opening_bins[b]) - opening_bins[b]
        unexplained = d - opening_diff - sum(comps[b].values())
        if unexplained:
            a.problems.append(f"bin {b}: unexplained book-physical difference {unexplained} kg")
        rec = result.reconciliation.get(b)
        expected = (closing, book[b], d, opening_diff, comps[b]["administrative"], comps[b]["survey_based"],
                    comps[b]["unposted_loss"], unexplained)
        if rec is None or (rec.physical_kg, rec.book_kg, rec.difference_kg, rec.opening_difference_kg,
                           rec.administrative_kg, rec.survey_based_kg, rec.unposted_loss_kg,
                           rec.unexplained_kg) != expected:
            a.problems.append(f"reconciliation {b}: reported {rec} differs from records {expected} "
                              f"(unexplained per records {unexplained} kg)")


def _audit_access(a, site, trucks, result) -> None:
    truck = {t.id: t for t in trucks}
    needs = {t.id: (t.requires_sampling if t.requires_sampling is not None else "sample" in getattr(site.sequences, t.activity))
             for t in trucks}
    occupancy = defaultdict(list)  # station bay -> [(start, end, truck)]
    sampling = []
    for rec in result.records:
        for s in rec.steps:
            if s.step in ("sample", "grade") and not needs.get(rec.truck_id, True):
                a.problems.append(f"{rec.truck_id} needs no sampling but has a {s.step} step")
            if s.unit and "#" in s.unit and s.started is not None:
                end = s.left if s.left is not None else (s.finished if s.finished is not None and rec.departed is not None else INF)
                occupancy[s.unit].append((s.started, end, rec.truck_id))
            if s.step == "sample" and s.started is not None and s.finished is not None:
                sampling.append((s.started, s.finished))
    for unit, spans in occupancy.items():
        spans.sort()
        for (s1, e1, t1), (s2, e2, t2) in zip(spans, spans[1:]):
            if t1 != t2 and s2 < e1:
                a.problems.append(f"bay {unit}: {t1} and {t2} occupy it together at {s2}")
    located = [e for e in site.equipment if e.type == "sampler" and e.located_at]
    if located:
        units = sum(int(e.cap or 1) for e in located)
        for t, _ in sampling:
            busy = sum(1 for s_, f_ in sampling if s_ <= t < f_)
            if busy > units:
                a.problems.append(f"{busy} co-located samplings at {t} with {units} sampling unit(s)")
    # Single-file areas: replay entries and exits in occurrence order; a normal exit must be the front truck.
    queues = defaultdict(list)
    for t, area, tid, kind, via in getattr(result, "single_file_log", []):
        q = queues[area]
        if kind == "enter":
            q.append(tid)
        elif tid not in q:
            a.problems.append(f"single-file {area}: {tid} left at {t} without having entered")
        else:
            if not via and q[0] != tid:
                a.problems.append(f"single-file {area}: {tid} left at {t} from behind {q[0]} without a bypass")
            q.remove(tid)
