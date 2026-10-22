"""Truck and grain flow: truck stations, tipping into hopper pits, and intake transfers to bins.

Build steps covered (docs/ENGINE_INTERFACES.md §7):
1. Stations: samplers, graders and weighbridges as pooled lanes (weighbridge direction respected); samples as
   separate entities matched back to their own truck; unlimited waiting areas (R5 default, a documented
   simplification); central dispatcher with strict FIFO or feasible-first per queue group.
2. Hopper pits (R2: ``full_load_space`` / ``empty_pit``, continuous drain A3, one grain per pit A4) and intake
   transfers pit -> conveyors/elevators -> bin on **exclusive** segments (R1 default), with bin reservations and
   partial fills. Every claim (lanes, pit space, segments, bin space) goes through the atomic reservation ledger.

Not built yet, and refused explicitly instead of being approximated:
- loading (``load`` step);
- concurrent feeds (``max_concurrent_feeds`` > 1, build step 4);
- commodity changeovers (R3, build step 3): a transfer that would put a different commodity on a segment stops
  the run with `NotYetSupported` rather than using a silent zero-minute changeover.

Interim (until R4 grades, build step 5): grain carries the placeholder grade ``*`` and bins accept every listed
commodity with that grade.

Events: completions and releases use RELEASE priority, the opening of the plant and pit-space re-checks CONTROL,
arrivals ARRIVAL. After every event the dispatcher reconsiders and the ledger invariants are checked.
"""
import math
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction

from ..config.routes import build_routes
from ..config.schema import SiteConfig
from ..domain.quantities import tonnes_to_kg
from ..domain.storage import GradedCommodity, MixingRules, StorageBin
from ..inputs.scripted import ScriptedTruck, schedule_arrivals
from .calendar import CONTROL, RELEASE, Calendar, Event
from .dispatcher import Dispatcher, DispatcherError, WaitReason
from .ledger import BinIncomingClaim, LaneClaim, PitSpaceClaim, ReservationLedger, SegmentClaim
from .pit import Lot, Pit
from .routing import RoutePlanner
from .service_times import ServiceTimes
from .time import m

UNGRADED = "*"
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
    started: int
    finished: int | None = None


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
    material_balance_kg: int  # opening + tipped - closing; must be 0
    violations: list[tuple[int, str]]  # (time, invariant problem) found after any event


def _hours_ms(hours: float) -> int:
    return m(Decimal(str(hours)) * 60)


def _transfer_ms(kg: int, rate_tph: Fraction) -> int:
    """Time to move `kg` at `rate_tph`, rounded up to the next whole millisecond."""
    return math.ceil(Fraction(kg) * 3600 / rate_tph)


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

        eq = site.equipment
        self.equipment = {e.id: e for e in eq}
        for e in eq:
            if e.type in ("conveyor", "elevator") and e.max_concurrent_feeds > 1:
                raise NotYetSupported(f"{e.name} allows {e.max_concurrent_feeds} concurrent feeds; concurrent feeds "
                                      "are build step 4.")
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
        self.transfers: list[TransferRecord] = []
        self.violations: list[tuple[int, str]] = []
        self._opening_kg = sum(b.tonnage_kg for b in self.bins.values()) + sum(p.committed_kg for p in self.pits.values())
        self._tipped_kg = 0
        if any(p.lots for p in self.pits.values()):
            self.cal.schedule(_hours_ms(site.hours.open), CONTROL, self._plant_opens, "plant opens")
        schedule_arrivals(self.cal, trucks, self._arrive)

    # ---- construction ----
    def _make_bin(self, e) -> StorageBin:
        accepts = frozenset(GradedCommodity(c, UNGRADED) for c in (e.commodities or []))
        opening_kg = tonnes_to_kg(e.inv) if e.inv else 0
        opening = GradedCommodity(e.inv_commodity, UNGRADED) if opening_kg else None
        return StorageBin(e.id, tonnes_to_kg(e.cap_t), accepts, MixingRules([]), opening_kg, opening)

    def _make_pit(self, e) -> Pit:
        lots = []
        if e.level0:
            lots.append(Lot(f"L0-{e.id}", None, GradedCommodity(e.level_commodity, UNGRADED), tonnes_to_kg(e.level0), 0))
        return Pit(e.id, tonnes_to_kg(e.cap_t), Fraction(str(e.rate)), e.tip_admission, set(e.commodities or []), lots)

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
            if "tip" in getattr(self.site.sequences, truck.activity) and not self._hopper_candidates(truck):
                name = self.names.get(truck.commodity, truck.commodity)
                raise ModelError(f"No hopper can take {name} (truck {truck.id}) and send it to a bin assigned to it.")

    def _grain(self, truck: ScriptedTruck) -> GradedCommodity:
        return GradedCommodity(truck.commodity, UNGRADED)

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
            for seg in segments:
                last = self.ledger.last_grain(seg)
                if last is not None and last != lot.grain:
                    raise NotYetSupported(
                        f"{self.equipment[seg].name} last carried {self.names.get(last.commodity, last.commodity)} and "
                        f"would now carry {self.names.get(lot.grain.commodity, lot.grain.commodity)}: commodity "
                        "changeover rules (R3) are build step 3.")
            b = self.bins[path[-1]]
            kg = min(lot.kg, b.free_space_kg)
            if kg <= 0:
                reasons.append(WaitReason("BIN_FULL", b.id, f"{b.id} is full"))
                continue
            claims = [SegmentClaim(s, lot.grain) for s in segments] + [BinIncomingClaim(b.id, lot.grain, kg)]
            got = self.ledger.try_reserve(req_id, claims, self.cal.now)
            if got:
                reasons.extend(got)
                continue
            rate = min([pit.rate_tph] + [Fraction(str(self.equipment[s].rate)) for s in segments])
            duration = _transfer_ms(kg, rate)
            pit.start_drain(kg, self.cal.now, duration)
            record = TransferRecord(req_id, pit_id, lot.id, lot.truck_id, path, b.id, kg, self.cal.now)
            self.transfers.append(record)
            self.cal.schedule(self.cal.now + duration, RELEASE, lambda c: self._intake_done(pit, b, record),
                              f"{lot.id}: {kg} kg from {pit_id} into {b.id}")
            return []
        unique: list[WaitReason] = []
        for r in reasons:
            if r not in unique:
                unique.append(r)
        return unique

    def _intake_done(self, pit: Pit, b: StorageBin, record: TransferRecord) -> None:
        b.receive(record.id, record.kg)
        pit.finish_drain(self.cal.now)
        self.ledger.release(record.id, self.cal.now, "completed")
        record.finished = self.cal.now
        self._intake_active.discard(pit.id)
        if pit.lots:
            self._submit_intake(pit.id)
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
            material_balance_kg=self._opening_kg + self._tipped_kg - closing,
            violations=list(self.violations))
