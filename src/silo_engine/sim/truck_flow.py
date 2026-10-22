"""Truck and grain flow: truck stations, tipping into hopper pits, and intake transfers to bins.

Build steps covered (docs/ENGINE_INTERFACES.md §7):
1. Stations: samplers, graders and weighbridges as pooled lanes (weighbridge direction respected); samples as
   separate entities matched back to their own truck; unlimited waiting areas (R5 default, a documented
   simplification); central dispatcher with strict FIFO or feasible-first per queue group.
2. Hopper pits (R2: ``full_load_space`` / ``empty_pit``, continuous drain A3, one grain per pit A4) and intake
   transfers pit -> conveyors/elevators -> bin on **exclusive** segments (R1 default), with bin reservations and
   partial fills. Every claim (lanes, pit space, segments, bin space) goes through the atomic reservation ledger.

3. Commodity-pair changeovers (R3) and route clear time (R1 ``clear_minutes``). A transfer's timeline is:
   route reserved -> changeover (longest segment, A5) -> grain flows (pit drains, bin receives at the end)
   -> clear time -> route released. Sites with missing or contradictory changeover rules do not run.

4. Concurrent feeds (R1 ``max_concurrent_feeds`` > 1). Each flowing transfer runs at the slowest of its pit's
   discharge rate and, for every segment, the segment rate divided by the streams *flowing* on it (A2, equal
   shares; a stream in its changeover holds a slot but no throughput). Whenever a flow starts or ends, remaining
   kilograms are updated exactly and completions rescheduled. Streams may share a segment only if their whole
   remaining route to the bin is the same (A1, ledger reason ``MERGE_PATH_DIFFERS``). Joining a segment that
   already carries the same grain needs no changeover.

Not built yet, and refused explicitly instead of being approximated:
- loading (``load`` step).

5. Grades (R4): grain carries commodity and grade (``config.grades.GradePolicy``); bins accept the grades listed
   for them; pits and bins combine grades only through the site's mixing rules; hopper choice and routing use the
   graded grain. The unloading sequence grades before tipping wherever grades are kept apart (checked by
   ``validate_rules``), so a truck's grade is used only after its own grading result is back.

Events: completions and releases use RELEASE priority, the opening of the plant and pit-space re-checks CONTROL,
arrivals ARRIVAL. After every event the dispatcher reconsiders and the ledger invariants are checked.
"""
import math
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction

from ..config.grades import GradePolicy
from ..config.routes import build_routes
from ..config.rules_validation import validate_rules
from ..config.schema import SiteConfig
from ..domain.changeover import ChangeoverMatrix
from ..domain.quantities import tonnes_to_kg
from ..domain.storage import GradedCommodity, StorageBin
from ..inputs.scripted import ScriptedTruck, schedule_arrivals
from .calendar import CONTROL, RELEASE, Calendar, Event
from .dispatcher import Dispatcher, DispatcherError, WaitReason
from .ledger import BinIncomingClaim, LaneClaim, PitSpaceClaim, ReservationLedger, SegmentClaim
from .pit import Lot, Pit
from .routing import RoutePlanner
from .service_times import ServiceTimes
from .time import m

STATION_TYPE = {"sample": "sampler", "weigh_in": "weighbridge", "weigh_out": "weighbridge"}
QUEUE_GROUP = {"sample": "sample", "grade": "grade", "weigh_in": "weigh", "weigh_out": "weigh",
               "tip": "tip", "intake": "intake"}
NOT_YET_SUPPORTED = ("load",)


class ModelError(ValueError):
    """The site cannot run these trucks (missing station, impossible sequence, unknown policy)."""


class NotYetSupported(ModelError):
    """A capability that a later build step will add."""


@dataclass
class _Unit:
    equipment_id: str
    lane: int
    type: str
    moves: str  # in, out, both

    @property
    def resource(self) -> str:
        return f"{self.equipment_id}#{self.lane}"

    def serves(self, step: str) -> bool:
        if step == "weigh_in":
            return self.moves in ("in", "both")
        if step == "weigh_out":
            return self.moves in ("out", "both")
        return True


@dataclass
class StepRecord:
    step: str
    entered: int  # reached the step and started waiting
    unit: str | None = None  # "WB1#0" (equipment id and lane), "H1" for tipping; None for a grading result
    started: int | None = None
    finished: int | None = None


@dataclass
class TruckRecord:
    truck_id: str
    activity: str
    arrived: int
    steps: list[StepRecord] = field(default_factory=list)
    departed: int | None = None


@dataclass
class TransferRecord:
    id: str
    pit: str
    lot_id: str
    truck_id: str | None
    path: list[str]
    bin: str
    kg: int
    started: int  # route reserved
    flow_started: int  # after the changeover
    changeover_segments: dict[str, int]  # segment -> changeover ms (0-minute changeovers included)
    finished: int | None = None  # last grain fed; grain in the bin
    released: int | None = None  # route free again (after clear time)


@dataclass(frozen=True)
class UnfinishedTruck:
    truck_id: str
    step: str
    in_service: bool
    arrived: int
    step_entered: int


@dataclass
class TruckFlowResult:
    records: list[TruckRecord]
    unfinished: list[UnfinishedTruck]
    samples: dict[str, tuple[str, int]]  # sample id -> (truck id, time the result came back)
    overtaken: dict[str, int]
    trace: list[Event]
    transfers: list[TransferRecord]
    bins: dict[str, tuple[int, GradedCommodity | None]]  # bin id -> (kg, identity)
    pits: dict[str, int]  # pit id -> kg (committed; a transfer in progress counts until it finishes)
    changeovers: dict[str, int]  # segment -> number of changeovers
    material_balance_kg: int  # opening + tipped - closing; must be 0
    violations: list[tuple[int, str]]  # (time, invariant problem) found after any event


def _hours_ms(hours: float) -> int:
    return m(Decimal(str(hours)) * 60)


def _kg_per_ms(rate_tph: Fraction) -> Fraction:
    return rate_tph * 1000 / 3_600_000


class TruckFlowModel:
    def __init__(self, site: SiteConfig, trucks: list[ScriptedTruck], times: ServiceTimes,
                 policy: str | dict[str, str]):
        self.site = site
        self.trucks = trucks
        self.times = times
        self.names = {c.id: c.name for c in site.commodities}
        groups = sorted(set(QUEUE_GROUP.values()))
        policies = {g: policy for g in groups} if isinstance(policy, str) else dict(policy)
        try:
            self.dispatcher = Dispatcher(policies)
        except DispatcherError as e:
            raise ModelError(f"Unknown dispatch policy: {e}") from None

        rules = validate_rules(site)
        if rules.errors:
            raise ModelError("The site's operating rules are incomplete:\n" + "\n".join(i.msg for i in rules.errors))
        self.changeover_matrix = ChangeoverMatrix.from_site(site)
        self.grades = GradePolicy(site)
        self.mixing = self.grades.mixing()
        eq = site.equipment
        self.equipment = {e.id: e for e in eq}
        self.units = [_Unit(e.id, lane, e.type, e.moves or "both")
                      for e in eq if e.type in ("sampler", "grader", "weighbridge") for lane in range(int(e.cap or 0))]
        self.bins = {e.id: self._make_bin(e) for e in eq if e.type == "bin"}
        self.pits = {e.id: self._make_pit(e) for e in eq if e.type == "hopper"}
        self.planner = RoutePlanner(build_routes(site), self.bins)
        self.ledger = ReservationLedger(
            lanes={u.resource for u in self.units} | {f"{h}:tip" for h in self.pits},
            segments={e.id: e.max_concurrent_feeds for e in eq if e.type in ("conveyor", "elevator")},
            pits=self.pits, bins=self.bins)
        self._check_trucks_can_run()

        self.cal = Calendar()
        self.records: dict[str, TruckRecord] = {}
        self._position: dict[str, int] = {}
        self._awaiting_result: dict[str, str] = {}
        self._results: dict[str, tuple[str, int]] = {}
        self._intake_active: set[str] = set()  # pits with an intake request waiting or a transfer running
        self._transfer_count = 0
        self._rechecks: set[tuple[str, int]] = set()
        self._flowing: dict[str, TransferRecord] = {}  # transfers whose grain is moving now
        self._completion: dict[str, Event] = {}  # transfer id -> its (re)scheduled completion event
        self.transfers: list[TransferRecord] = []
        self.violations: list[tuple[int, str]] = []
        self._opening_kg = sum(b.tonnage_kg for b in self.bins.values()) + sum(p.committed_kg for p in self.pits.values())
        self._tipped_kg = 0
        if any(p.lots for p in self.pits.values()):
            self.cal.schedule(_hours_ms(site.hours.open), CONTROL, self._plant_opens, "plant opens")
        schedule_arrivals(self.cal, trucks, self._arrive)

    # ---- construction ----
    def _make_bin(self, e) -> StorageBin:
        opening_kg = tonnes_to_kg(e.inv) if e.inv else 0
        opening = self.grades.grain(e.inv_commodity, e.inv_grade) if opening_kg else None
        return StorageBin(e.id, tonnes_to_kg(e.cap_t), self.grades.bin_accepts(e), self.mixing, opening_kg, opening)

    def _make_pit(self, e) -> Pit:
        lots = []
        if e.level0:
            grain = self.grades.grain(e.level_commodity, e.level_grade)
            lots.append(Lot(f"L0-{e.id}", None, grain, tonnes_to_kg(e.level0), 0))
        return Pit(e.id, tonnes_to_kg(e.cap_t), Fraction(str(e.rate)), e.tip_admission, set(e.commodities or []), lots,
                   self.mixing)

    def _check_trucks_can_run(self) -> None:
        for act in sorted({t.activity for t in self.trucks}):
            steps = getattr(self.site.sequences, act)
            for step in steps:
                if step in NOT_YET_SUPPORTED:
                    raise NotYetSupported(f"The '{step}' step is not built yet (needed by {act} trucks).")
            for i, step in enumerate(steps):
                if step == "grade":
                    if "sample" not in steps[:i]:
                        raise ModelError(f"{act} trucks are graded without an earlier sample step.")
                    if not any(u.type == "grader" for u in self.units):
                        raise ModelError(f"{act} trucks need a grader, but none is configured.")
                elif step in STATION_TYPE:
                    kind = STATION_TYPE[step]
                    if not any(u.type == kind and u.serves(step) for u in self.units):
                        need = {"weigh_in": "a weighbridge that weighs in", "weigh_out": "a weighbridge that weighs out"}
                        raise ModelError(f"{act} trucks need {need.get(step, 'a ' + kind)}, but none is configured.")
        for truck in self.trucks:
            if truck.commodity is not None:
                name = self.names.get(truck.commodity, truck.commodity)
                if self.grades.is_graded(truck.commodity):
                    if truck.grade is None and self.grades.segregated(truck.commodity):
                        raise ModelError(f"Truck {truck.id} brings {name}, which is graded; give its grade.")
                    if truck.grade is not None and truck.grade not in self.grades.grades[truck.commodity]:
                        raise ModelError(f"Truck {truck.id} has {name} grade {truck.grade}, which is not one of "
                                         "its grades.")
                elif truck.grade is not None:
                    raise ModelError(f"Truck {truck.id} gives a grade for {name}, which has no grades.")
            if "tip" in getattr(self.site.sequences, truck.activity) and not self._hopper_candidates(truck):
                name = self.names.get(truck.commodity, truck.commodity)
                raise ModelError(f"No hopper can take {name} (truck {truck.id}) and send it to a bin assigned to it.")

    def _grain(self, truck: ScriptedTruck) -> GradedCommodity:
        return self.grades.grain(truck.commodity, truck.grade)

    def _hopper_candidates(self, truck: ScriptedTruck) -> list[Pit]:
        grain = self._grain(truck)
        ok = [p for p in self.pits.values() if truck.commodity in p.accepts and self.planner.has_intake_route(p.id, grain)]
        # Prefer a pit already holding this grain (prototype rule), otherwise configuration order.
        return [p for p in ok if p.lots and p.identity() == grain] + [p for p in ok if not (p.lots and p.identity() == grain)]

    # ---- event plumbing ----
    def _after_event(self) -> None:
        self.dispatcher.reconsider(self.cal.now)
        for problem in self.ledger.check_invariants(self.cal.now):
            self.violations.append((self.cal.now, problem))

    def _plant_opens(self, cal: Calendar) -> None:
        for pit in self.pits.values():
            if pit.lots:
                self._submit_intake(pit.id)
        self._after_event()

    # ---- trucks ----
    def _arrive(self, cal: Calendar, truck: ScriptedTruck) -> None:
        self.records[truck.id] = TruckRecord(truck.id, truck.activity, cal.now)
        self._position[truck.id] = -1
        self._advance(truck)
        self._after_event()

    def _truck(self, truck_id: str) -> ScriptedTruck:
        return next(t for t in self.trucks if t.id == truck_id)

    def _advance(self, truck: ScriptedTruck) -> None:
        rec = self.records[truck.id]
        steps = getattr(self.site.sequences, rec.activity)
        self._position[truck.id] += 1
        if self._position[truck.id] >= len(steps):
            rec.departed = self.cal.now
            return
        step = steps[self._position[truck.id]]
        step_rec = StepRecord(step, self.cal.now)
        rec.steps.append(step_rec)
        if step == "grade":
            sample_id = f"S-{truck.id}"
            if sample_id in self._results:
                self._result_reached_truck(truck, step_rec)
            else:
                self._awaiting_result[truck.id] = sample_id
            return
        attempt = (lambda now, tr=truck, sr=step_rec: self._try_tip(tr, sr)) if step == "tip" else \
                  (lambda now, tr=truck, sr=step_rec: self._try_truck_station(tr, sr))
        self.dispatcher.submit(f"{truck.id}/{step}", QUEUE_GROUP[step], self.cal.now, attempt)

    def _result_reached_truck(self, truck: ScriptedTruck, step_rec: StepRecord) -> None:
        step_rec.started = step_rec.finished = self.cal.now
        self._advance(truck)

    def _try_lane(self, reservation_id: str, kind: str, step: str) -> tuple[_Unit | None, list[WaitReason]]:
        compatible = [u for u in self.units if u.type == kind and u.serves(step)]
        for u in compatible:
            if self.ledger.lane_free(u.resource):
                if self.ledger.try_reserve(reservation_id, [LaneClaim(u.resource)], self.cal.now) == []:
                    return u, []
        ids = sorted({u.equipment_id for u in compatible})
        return None, [WaitReason("EQUIPMENT_BUSY", ",".join(ids), f"{', '.join(ids)} busy")]

    def _try_truck_station(self, truck: ScriptedTruck, step_rec: StepRecord) -> list[WaitReason]:
        res_id = f"{truck.id}/{step_rec.step}"
        unit, reasons = self._try_lane(res_id, STATION_TYPE[step_rec.step], step_rec.step)
        if unit is None:
            return reasons
        step_rec.unit, step_rec.started = unit.resource, self.cal.now
        end = self.cal.now + self.times.duration_ms(truck.id, step_rec.step, unit.equipment_id)
        self.cal.schedule(end, RELEASE, lambda c: self._truck_service_done(truck, step_rec, res_id),
                          f"{truck.id} finishes {step_rec.step} at {unit.equipment_id}")
        return []

    def _truck_service_done(self, truck: ScriptedTruck, step_rec: StepRecord, res_id: str) -> None:
        self.ledger.release(res_id, self.cal.now, "completed")
        step_rec.finished = self.cal.now
        if step_rec.step == "sample":
            sample_id = f"S-{truck.id}"
            self.dispatcher.submit(f"{sample_id}/grade", "grade", self.cal.now,
                                   lambda now: self._try_grade(sample_id, truck))
        self._advance(truck)
        self._after_event()

    # ---- samples ----
    def _try_grade(self, sample_id: str, truck: ScriptedTruck) -> list[WaitReason]:
        res_id = f"{sample_id}/grade"
        unit, reasons = self._try_lane(res_id, "grader", "grade")
        if unit is None:
            return reasons
        end = self.cal.now + self.times.duration_ms(truck.id, "grade", unit.equipment_id)
        self.cal.schedule(end, RELEASE, lambda c: self._grading_done(sample_id, truck, res_id),
                          f"{sample_id} graded at {unit.equipment_id}")
        return []

    def _grading_done(self, sample_id: str, truck: ScriptedTruck, res_id: str) -> None:
        self.ledger.release(res_id, self.cal.now, "completed")
        self._results[sample_id] = (truck.id, self.cal.now)
        waiting_for = self._awaiting_result.get(truck.id)
        if waiting_for is not None:
            if waiting_for != sample_id:  # cannot happen with id-keyed samples; guards future changes
                raise RuntimeError(f"Sample {sample_id} offered to {truck.id}, which waits for {waiting_for}")
            del self._awaiting_result[truck.id]
            self._result_reached_truck(truck, self.records[truck.id].steps[-1])
        self._after_event()

    # ---- tipping ----
    def _try_tip(self, truck: ScriptedTruck, step_rec: StepRecord) -> list[WaitReason]:
        grain, kg, res_id = self._grain(truck), truck.kg, f"{truck.id}/tip"
        reasons: list[WaitReason] = []
        for pit in self._hopper_candidates(truck):
            got = self.ledger.try_reserve(res_id, [LaneClaim(f"{pit.id}:tip"), PitSpaceClaim(pit.id, grain, kg)], self.cal.now)
            if not got:
                step_rec.unit, step_rec.started = pit.id, self.cal.now
                end = self.cal.now + self.times.duration_ms(truck.id, "tip", pit.id)
                self.cal.schedule(end, RELEASE, lambda c, p=pit: self._tip_done(truck, step_rec, p, res_id),
                                  f"{truck.id} finishes tipping into {pit.id}")
                return []
            reasons.extend(got)
            if any(r.code == "PIT_SPACE" for r in got):  # re-evaluate when space appears, even if other reasons remain
                self._schedule_space_recheck(pit, kg)
        return reasons

    def _schedule_space_recheck(self, pit: Pit, kg: int) -> None:
        when = pit.time_space_available(self.cal.now, kg)
        if when is not None and when > self.cal.now and (pit.id, when) not in self._rechecks:
            self._rechecks.add((pit.id, when))
            self.cal.schedule(when, CONTROL, lambda c: self._after_event(), f"space check {pit.id}")

    def _tip_done(self, truck: ScriptedTruck, step_rec: StepRecord, pit: Pit, res_id: str) -> None:
        pit.claim_to_lot(res_id, Lot(f"L-{truck.id}", truck.id, self._grain(truck), truck.kg, self.cal.now))
        self.ledger.release(res_id, self.cal.now, "completed")
        self._tipped_kg += truck.kg
        step_rec.finished = self.cal.now
        if pit.id not in self._intake_active:
            self._submit_intake(pit.id)
        self._advance(truck)
        self._after_event()

    # ---- intake transfers ----
    def _submit_intake(self, pit_id: str) -> None:
        self._intake_active.add(pit_id)
        self._transfer_count += 1
        req_id = f"{pit_id}/intake#{self._transfer_count}"
        self.dispatcher.submit(req_id, "intake", self.cal.now, lambda now: self._try_intake(pit_id, req_id))

    def _try_intake(self, pit_id: str, req_id: str) -> list[WaitReason]:
        pit = self.pits[pit_id]
        lot = pit.lots[0]
        candidates = self.planner.intake_candidates(pit_id, lot.grain)
        if not candidates:
            return [WaitReason("NO_PHYSICAL_ROUTE", pit_id, f"no route from {pit_id} to a bin for this grain")]
        reasons: list[WaitReason] = []
        for path in candidates:
            segments = path[1:-1]
            b = self.bins[path[-1]]
            kg = min(lot.kg, b.free_space_kg)
            if kg <= 0:
                reasons.append(WaitReason("BIN_FULL", b.id, f"{b.id} is full"))
                continue
            changeovers = self._changeovers(segments, lot.grain)  # before reserving: joining needs no changeover
            claims = [SegmentClaim(s, lot.grain, tuple(path[i:])) for i, s in enumerate(path) if 0 < i < len(path) - 1]
            claims.append(BinIncomingClaim(b.id, lot.grain, kg))
            got = self.ledger.try_reserve(req_id, claims, self.cal.now)
            if got:
                reasons.extend(got)
                continue
            flow_start = max(self.cal.now + max(changeovers.values(), default=0),  # own changeovers, in parallel (A5)
                             self._segments_ready(segments))  # not before a changeover already under way finishes
            pit.start_drain(kg, flow_start)
            record = TransferRecord(req_id, pit_id, lot.id, lot.truck_id, path, b.id, kg, self.cal.now, flow_start,
                                    changeovers)
            self.transfers.append(record)
            if flow_start == self.cal.now:
                self._start_flow(record)
            else:
                self.cal.schedule(flow_start, CONTROL, lambda c: (self._start_flow(record), self._after_event()),
                                  f"{record.id}: changeover done, grain flows")
            return []
        unique: list[WaitReason] = []
        for r in reasons:
            if r not in unique:
                unique.append(r)
        return unique

    def _changeovers(self, segments: list[str], grain: GradedCommodity) -> dict[str, int]:
        """Changeover ms per segment whose last grain differs (first use of a segment needs none)."""
        needed = {}
        for seg in segments:
            last = self.ledger.last_grain(seg)
            if last is None or last == grain or self.ledger.segment_streams(seg):
                continue  # first use, same grain, or already carrying grain (the commodity lock makes it ours)
            minutes = self.changeover_matrix.required_minutes(seg, last, grain)
            if minutes is None:  # validate_rules guarantees a rule; this guards against inconsistent use
                raise ModelError(f"No changeover rule for {last.commodity} -> {grain.commodity} on {seg}.")
            needed[seg] = m(minutes)
        return needed

    def _segments_ready(self, segments: list[str]) -> int:
        """When grain may flow on `segments`: after the flow start of every unfinished transfer already using any of
        them (a stream joining during another stream's changeover must wait for it)."""
        shared = set(segments)
        return max((x.flow_started for x in self.transfers
                    if x.finished is None and shared & set(x.path[1:-1])), default=self.cal.now)

    def _start_flow(self, record: TransferRecord) -> None:
        self._flowing[record.id] = record
        self._recompute_rates()

    def _recompute_rates(self) -> None:
        """Equal shares (A2) for every flowing transfer; reschedule completions whose rate changed."""
        now = self.cal.now
        flowing_on: dict[str, int] = {}
        for rec in self._flowing.values():
            for seg in rec.path[1:-1]:
                flowing_on[seg] = flowing_on.get(seg, 0) + 1
        for rec in self._flowing.values():
            pit = self.pits[rec.pit]
            rate_tph = min([pit.rate_tph] + [Fraction(str(self.equipment[s].rate)) / flowing_on[s] for s in rec.path[1:-1]])
            rate = _kg_per_ms(rate_tph)
            if rec.id in self._completion and pit.draining.rate == rate:
                continue
            pit.set_rate(now, rate)
            if rec.id in self._completion:
                self.cal.cancel(self._completion[rec.id])
            end = now + math.ceil(pit.remaining_drain_kg(now) / rate)
            b = self.bins[rec.bin]
            self._completion[rec.id] = self.cal.schedule(
                end, RELEASE, lambda c, p=pit, bb=b, r=rec: self._intake_done(p, bb, r),
                f"{rec.lot_id}: {rec.kg} kg from {rec.pit} into {rec.bin}")

    def _intake_done(self, pit: Pit, b: StorageBin, record: TransferRecord) -> None:
        del self._flowing[record.id]
        del self._completion[record.id]
        b.receive(record.id, record.kg)
        pit.finish_drain(self.cal.now)
        record.finished = self.cal.now
        self._recompute_rates()  # the others may speed up
        self._intake_active.discard(pit.id)
        if pit.lots:
            self._submit_intake(pit.id)
        clear = max((m(Decimal(str(self.equipment[s].clear_minutes))) for s in record.path[1:-1]), default=0)
        if clear:
            self.cal.schedule(self.cal.now + clear, RELEASE, lambda c: self._route_released(record),
                              f"route clear after {record.id}")
        else:
            self._route_released(record, in_event=False)
        self._after_event()

    def _route_released(self, record: TransferRecord, in_event: bool = True) -> None:
        self.ledger.release(record.id, self.cal.now, "completed")
        record.released = self.cal.now
        if in_event:
            self._after_event()

    # ---- running and results ----
    def run(self, until: int | None = None) -> TruckFlowResult:
        self.cal.run(until)
        return self.result()

    def waiting_reasons(self) -> dict[str, list[WaitReason]]:
        return self.dispatcher.waiting_reasons()

    def result(self) -> TruckFlowResult:
        unfinished = []
        for rec in self.records.values():
            if rec.departed is None:
                s = rec.steps[-1]
                in_service = s.started is not None and s.finished is None and s.unit is not None
                unfinished.append(UnfinishedTruck(rec.truck_id, s.step, in_service, rec.arrived, s.entered))
        closing = sum(b.tonnage_kg for b in self.bins.values()) + sum(p.committed_kg for p in self.pits.values())
        return TruckFlowResult(
            records=list(self.records.values()), unfinished=unfinished, samples=dict(self._results),
            overtaken=self.dispatcher.overtaken(), trace=list(self.cal.log), transfers=list(self.transfers),
            bins={bid: (b.tonnage_kg, b.identity) for bid, b in self.bins.items()},
            pits={pid: p.committed_kg for pid, p in self.pits.items()},
            changeovers={seg: n for seg in self.ledger.segment_ids()
                         if (n := sum(1 for x in self.transfers if seg in x.changeover_segments))},
            material_balance_kg=self._opening_kg + self._tipped_kg - closing,
            violations=list(self.violations))
