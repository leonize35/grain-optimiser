"""Truck flow through truck stations: sampling, grading and weighbridges (build step 1).

Scope of this step (docs/ENGINE_INTERFACES.md §7, item 1):
- stations are pooled units (`cap` lanes per sampler, grader or weighbridge); weighbridges respect direction
  (`moves`: in, out or both); the first free compatible unit in configuration order is used;
- waiting areas are unlimited (R5 default, a documented simplification); a truck leaves a station when its
  service ends;
- samples are separate entities: sampling creates sample ``S-<truck>``, which queues for a grader; a truck at
  its ``grade`` step waits until *its own* result is back (results may return in any order);
- every waiting request goes through the central dispatcher (strict FIFO or feasible-first per queue group);
- tipping and loading are not built yet and are refused explicitly.

Events: service completions use RELEASE priority, arrivals ARRIVAL priority. The dispatcher reconsiders after
every event that changes what is possible.
"""
from dataclasses import dataclass, field

from ..config.schema import SiteConfig
from ..inputs.scripted import ScriptedTruck, schedule_arrivals
from .calendar import RELEASE, Calendar, Event
from .dispatcher import Dispatcher, DispatcherError, WaitReason
from .service_times import ServiceTimes

STATION_TYPE = {"sample": "sampler", "weigh_in": "weighbridge", "weigh_out": "weighbridge"}
QUEUE_GROUP = {"sample": "sample", "grade": "grade", "weigh_in": "weigh", "weigh_out": "weigh"}
NOT_YET_SUPPORTED = ("tip", "load")


class ModelError(ValueError):
    """The site cannot run these trucks (missing station, impossible sequence, unknown policy)."""


class NotYetSupported(ModelError):
    """A step that a later build step will add."""


@dataclass
class _Unit:
    equipment_id: str
    lane: int
    type: str
    moves: str  # in, out, both
    busy_with: str | None = None

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
    unit: str | None = None  # "WB1#0" (equipment id and lane); None for waiting on a grading result
    started: int | None = None
    finished: int | None = None


@dataclass
class TruckRecord:
    truck_id: str
    activity: str
    arrived: int
    steps: list[StepRecord] = field(default_factory=list)
    departed: int | None = None


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


class TruckFlowModel:
    def __init__(self, site: SiteConfig, trucks: list[ScriptedTruck], times: ServiceTimes,
                 policy: str | dict[str, str]):
        self.site = site
        self.trucks = trucks
        self.times = times
        groups = sorted(set(QUEUE_GROUP.values()))
        policies = {g: policy for g in groups} if isinstance(policy, str) else dict(policy)
        try:
            self.dispatcher = Dispatcher(policies)
        except DispatcherError as e:
            raise ModelError(f"Unknown dispatch policy: {e}") from None
        self.units = [_Unit(e.id, lane, e.type, e.moves or "both")
                      for e in site.equipment if e.type in ("sampler", "grader", "weighbridge")
                      for lane in range(int(e.cap or 0))]
        self._check_trucks_can_run()
        self.cal = Calendar()
        self.records: dict[str, TruckRecord] = {}
        self._position: dict[str, int] = {}
        self._awaiting_result: dict[str, str] = {}  # truck id -> sample id it waits for
        self._results: dict[str, tuple[str, int]] = {}  # sample id -> (truck id, result time)
        schedule_arrivals(self.cal, trucks, self._arrive)

    # ---- set-up checks ----
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

    # ---- truck movement ----
    def _arrive(self, cal: Calendar, truck: ScriptedTruck) -> None:
        self.records[truck.id] = TruckRecord(truck.id, truck.activity, cal.now)
        self._position[truck.id] = -1
        self._advance(truck.id)
        self.dispatcher.reconsider(cal.now)

    def _advance(self, truck_id: str) -> None:
        rec = self.records[truck_id]
        steps = getattr(self.site.sequences, rec.activity)
        self._position[truck_id] += 1
        if self._position[truck_id] >= len(steps):
            rec.departed = self.cal.now
            return
        step = steps[self._position[truck_id]]
        step_rec = StepRecord(step, self.cal.now)
        rec.steps.append(step_rec)
        if step == "grade":
            sample_id = f"S-{truck_id}"
            if sample_id in self._results:
                self._result_reached_truck(truck_id, step_rec)
            else:
                self._awaiting_result[truck_id] = sample_id
            return
        self.dispatcher.submit(f"{truck_id}/{step}", QUEUE_GROUP[step], self.cal.now,
                               lambda now, tid=truck_id, sr=step_rec: self._try_truck_station(tid, sr))

    def _result_reached_truck(self, truck_id: str, step_rec: StepRecord) -> None:
        step_rec.started = step_rec.finished = self.cal.now
        self._advance(truck_id)

    def _free_unit(self, step: str) -> tuple[_Unit | None, list[WaitReason]]:
        kind = "grader" if step == "grade" else STATION_TYPE[step]
        compatible = [u for u in self.units if u.type == kind and u.serves(step)]
        for u in compatible:
            if u.busy_with is None:
                return u, []
        ids = sorted({u.equipment_id for u in compatible})
        return None, [WaitReason("EQUIPMENT_BUSY", ",".join(ids), f"{', '.join(ids)} busy")]

    def _try_truck_station(self, truck_id: str, step_rec: StepRecord) -> list[WaitReason]:
        unit, reasons = self._free_unit(step_rec.step)
        if unit is None:
            return reasons
        unit.busy_with = truck_id
        step_rec.unit, step_rec.started = f"{unit.equipment_id}#{unit.lane}", self.cal.now
        end = self.cal.now + self.times.duration_ms(truck_id, step_rec.step, unit.equipment_id)
        self.cal.schedule(end, RELEASE, lambda c: self._truck_service_done(truck_id, step_rec, unit),
                          f"{truck_id} finishes {step_rec.step} at {unit.equipment_id}")
        return []

    def _truck_service_done(self, truck_id: str, step_rec: StepRecord, unit: _Unit) -> None:
        unit.busy_with = None
        step_rec.finished = self.cal.now
        if step_rec.step == "sample":
            sample_id = f"S-{truck_id}"
            self.dispatcher.submit(f"{sample_id}/grade", "grade", self.cal.now,
                                   lambda now: self._try_grade(sample_id, truck_id))
        self._advance(truck_id)
        self.dispatcher.reconsider(self.cal.now)

    # ---- samples ----
    def _try_grade(self, sample_id: str, truck_id: str) -> list[WaitReason]:
        unit, reasons = self._free_unit("grade")
        if unit is None:
            return reasons
        unit.busy_with = sample_id
        end = self.cal.now + self.times.duration_ms(truck_id, "grade", unit.equipment_id)
        self.cal.schedule(end, RELEASE, lambda c: self._grading_done(sample_id, truck_id, unit),
                          f"{sample_id} graded at {unit.equipment_id}")
        return []

    def _grading_done(self, sample_id: str, truck_id: str, unit: _Unit) -> None:
        unit.busy_with = None
        self._results[sample_id] = (truck_id, self.cal.now)
        waiting_for = self._awaiting_result.get(truck_id)
        if waiting_for is not None:
            if waiting_for != sample_id:  # cannot happen with id-keyed samples; guards future changes
                raise RuntimeError(f"Sample {sample_id} offered to {truck_id}, which waits for {waiting_for}")
            del self._awaiting_result[truck_id]
            self._result_reached_truck(truck_id, self.records[truck_id].steps[-1])
        self.dispatcher.reconsider(self.cal.now)

    # ---- running ----
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
        return TruckFlowResult(list(self.records.values()), unfinished, dict(self._results),
                               self.dispatcher.overtaken(), list(self.cal.log))
