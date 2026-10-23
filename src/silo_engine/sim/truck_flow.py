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

6. Waiting areas and blocking (R5, A6). Trucks follow a path of waiting areas and steps and hold one place at a
   time (an area place or a station/hopper lane), giving it up only when they have the next. A truck that cannot
   move on stays on its station and blocks it. ``reserve_next_space`` reserves the place in the next finite area
   together with the service; ``detect_only`` does not, and relies on stall detection. Without a configured path,
   unlimited implicit areas between steps reproduce the non-blocking behaviour (listed in the run's assumptions).
   In every mode, if work is waiting and nothing but new arrivals is left to happen, the run stops and reports a
   stall with each waiting request and its reasons.

7. Operating hours and unfinished work (R6). The gate admits trucks from opening until the admission cut-off;
   earlier arrivals wait at the gate, later ones wait for the next day or are turned away. Services start only
   until closing + overtime (the hard stop); a service already running then is completed (A7). Grain transfers
   continue after closing unless the site says otherwise. At the hard stop, trucks still on site carry over
   (keep their place) or are sent away. ``days`` sets the horizon. Every truck ends in exactly one of: completed,
   turned away, or unfinished (with its waiting time so far, measured to the end of the last day's service).

8. Loading trucks. A loading truck reserves, as one transaction, a load point (its place), a load-out route
   (bin -> conveyors/elevators -> load point) and its tonnage of stock in one bin holding its commodity (and grade,
   if the order names one). Route preference: fewest changeover minutes, then shortest. Load time = setup +
   changeover + tonnes / route rate. The stock leaves the bin when loading ends; the route is released then (after
   any clear time), even if the truck must stay at the load point because there is no space ahead.

Fairness (Q1, reported only; queue selection is unchanged): every result carries per-truck waiting, overtakes by
later arrivals and completion, per-commodity summaries, and the number of starved trucks against the site's
configurable threshold.

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
from .calendar import ARRIVAL, CONTROL, RELEASE, Calendar, Event
from .dispatcher import Dispatcher, DispatcherError, WaitReason
from .ledger import (AreaClaim, BinIncomingClaim, BinOutgoingClaim, LaneClaim, PitSpaceClaim, ReservationLedger,
                     SegmentClaim)
from .pit import Lot, Pit
from .routing import RoutePlanner
from .service_times import ServiceTimes
from .time import MS_PER_DAY, MS_PER_MINUTE, m

STATION_TYPE = {"sample": "sampler", "weigh_in": "weighbridge", "weigh_out": "weighbridge"}
QUEUE_GROUP = {"sample": "sample", "grade": "grade", "weigh_in": "weigh", "weigh_out": "weigh",
               "tip": "tip", "intake": "intake", "move": "move", "load": "load"}
NOT_YET_SUPPORTED: tuple[str, ...] = ()
ACTIVITY_LABEL = {"unload": "Unloading", "load": "Loading", "weigh": "Weighbridge-only"}


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
    finished: int | None = None  # service ended
    left: int | None = None  # truck physically left the station; later than `finished` when it was blocked (R5)


@dataclass
class TruckRecord:
    truck_id: str
    activity: str
    arrived: int  # at the gate
    steps: list[StepRecord] = field(default_factory=list)
    departed: int | None = None
    admitted: int | None = None  # let in through the gate (later than `arrived` for early or late arrivals)
    turned_away: str | None = None  # why the truck left without finishing
    turned_away_at: int | None = None


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


@dataclass
class LoadRecord:
    id: str
    truck_id: str
    bin: str
    path: list[str]  # bin, ..., load point
    kg: int
    started: int  # load point, route and stock reserved; setup begins
    flow_started: int  # after setup and any changeover
    changeover_segments: dict[str, int]
    finished: int | None = None  # truck loaded; stock left the bin
    released: int | None = None  # route free again (after clear time)


@dataclass(frozen=True)
class UnfinishedTruck:
    truck_id: str
    step: str
    in_service: bool
    arrived: int
    step_entered: int
    location: str | None = None  # reservation holding the truck's place (area or station lane), None if outside
    admitted: bool = True  # False: still waiting outside the gate


@dataclass(frozen=True)
class ActivitySummary:
    """R6 reporting per truck activity. Turnaround is gate arrival to departure, in minutes."""
    completed: int
    unfinished: int
    turned_away: int
    mean_turnaround_min: float | None
    median_turnaround_min: float | None
    p90_turnaround_min: float | None
    max_turnaround_min: float | None
    unfinished_waiting_min: list[float]  # time on site so far, measured to the end of the run's last service day
    # Completed plus unfinished (waiting so far): a lower bound, because unfinished trucks are not done yet.
    mean_turnaround_incl_unfinished_min: float | None


@dataclass(frozen=True)
class TruckMetrics:
    """Fairness record for one truck (Q1). Waiting = time on site not in service, up to departure or the end of
    the run (gate waits, queues, waiting for a grading result, and time blocked on a station all count).

    Overtaking: truck X overtakes truck Y when X starts a step while Y is still waiting in the same queue group,
    Y entered that queue before X (queue position), and Y arrived at the gate before X (arrival order; equal
    arrival times keep script order). Completion order plays no part: finishing first is not overtaking."""
    truck_id: str
    activity: str
    commodity: str | None
    grade: str | None  # grain class
    arrived: int  # at the gate
    gate_admitted: int | None  # let in through the gate (None: never admitted)
    queue_entered: dict[str, int]  # step -> time the truck reached it and began waiting (first visit)
    hopper_queue_entered: int | None  # joined the hopper queue (unloading trucks)
    hopper_admitted: int | None  # started tipping (None: never reached a hopper)
    departed: int | None
    total_waiting_min: float
    hopper_wait_min: float | None  # queueing for a hopper (unloading trucks)
    overtaken_by_later: int  # times a later-arriving truck started a step this truck was already waiting for
    overtaken_at_hopper: int  # the part of overtaken_by_later where the step was tipping
    status: str  # "completed", "unfinished" (on site or at the gate when the run ended) or "turned_away"
    unfinished: bool
    turned_away: bool
    starved: bool  # against the site's starvation threshold (reporting only; never affects the simulation)


@dataclass(frozen=True)
class CommodityFairness:
    """Waits include unfinished trucks' waiting so far (so they are lower bounds). Percentiles: nearest rank."""
    trucks: int
    mean_total_wait_min: float | None
    max_total_wait_min: float | None
    mean_hopper_wait_min: float | None
    max_hopper_wait_min: float | None
    mean_turnaround_min: float | None  # completed trucks only
    still_waiting: int  # unfinished at the end of the run
    median_total_wait_min: float | None = None
    p95_total_wait_min: float | None = None
    median_hopper_wait_min: float | None = None
    p95_hopper_wait_min: float | None = None
    mean_overtaken: float | None = None
    max_overtaken: int = 0
    max_overtaken_at_hopper: int = 0
    starved: int = 0
    turned_away: int = 0


@dataclass(frozen=True)
class ActivityFairness:
    by_commodity: dict[str, CommodityFairness]  # commodity id ("none" for weighbridge-only trucks)
    max_overtaken: int
    most_overtaken_truck: str | None
    starved: int
    starvation_wait_minutes: float
    starvation_overtakes: int | None


@dataclass(frozen=True)
class Stall:
    """Waiting work that nothing left in the simulation can unblock (deadlock, or a plant jammed for good)."""
    time: int
    waiting: dict[str, list[WaitReason]]


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
    stall: Stall | None  # set when the run stopped because nothing could move any more
    assumptions: list[str]  # simplifications this run relied on (e.g. unlimited waiting space)
    area_peak: dict[str, int]  # configured waiting area -> most trucks in it at once
    summary: dict[str, ActivitySummary]  # activity -> completed / unfinished / turned away and turnaround
    received_kg: int = 0  # grain tipped by trucks during the run
    truck_metrics: dict[str, TruckMetrics] = field(default_factory=dict)
    fairness: dict[str, ActivityFairness] = field(default_factory=dict)
    loads: list[LoadRecord] = field(default_factory=list)
    dispatched_kg: int = 0  # grain loaded onto trucks during the run


def _hours_ms(hours: float) -> int:
    return m(Decimal(str(hours)) * 60)


def _kg_per_ms(rate_tph: Fraction) -> Fraction:
    return rate_tph * 1000 / 3_600_000


class TruckFlowModel:
    def __init__(self, site: SiteConfig, trucks: list[ScriptedTruck], times: ServiceTimes,
                 policy: str | dict[str, str], days: int = 1):
        if days < 1:
            raise ModelError("A run covers at least one day.")
        self.site = site
        self.days = days
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
        self._area_caps: dict[str, int | None] = {a.id: a.capacity for a in site.truck_areas}
        used = [act for act in ACTIVITY_LABEL if any(t.activity == act for t in trucks)]
        self.paths = {act: self._build_path(act) for act in used}
        self.ledger = ReservationLedger(
            lanes={u.resource for u in self.units} | {f"{h}:tip" for h in self.pits}
                  | {f"{e.id}:load" for e in eq if e.type == "loadpoint"},
            segments={e.id: e.max_concurrent_feeds for e in eq if e.type in ("conveyor", "elevator")},
            pits=self.pits, bins=self.bins, areas=self._area_caps)
        self.assumptions = [f"{ACTIVITY_LABEL[act]} trucks have unlimited waiting space between steps "
                            "(no truck path configured)." for act in used if not getattr(site.truck_paths, act)]
        self.assumptions += [f"Waiting area {a.name} has unlimited space." for a in site.truck_areas if a.capacity is None]
        eod, chosen = site.end_of_day, site.end_of_day.model_fields_set
        if "unfinished_trucks" not in chosen and eod.unfinished_trucks == "carry_over":
            self.assumptions.append("Unfinished trucks stay on site and continue the next operating day (default).")
        if "late_arrivals" not in chosen and eod.late_arrivals == "queue_for_next_day":
            self.assumptions.append("Trucks arriving after the admission cut-off wait for the next operating day (default).")
        if "transfers_after_close" not in chosen and eod.transfers_after_close:
            self.assumptions.append("Grain transfers continue after closing until the pits are empty (default).")
        self.assumptions.append("A service already running at the hard stop is completed (assumption A7).")
        if "starvation_wait_minutes" not in site.fairness.model_fields_set:
            self.assumptions.append(f"A truck counts as starved after waiting {site.fairness.starvation_wait_minutes:g} "
                                    "min in total (default reporting threshold).")
        h = site.hours
        self.windows = []  # per day: (open, admission cut-off, hard stop) in ms
        for d in range(days):
            base = d * MS_PER_DAY
            cutoff = h.admission_cutoff if h.admission_cutoff is not None else h.close
            self.windows.append((base + _hours_ms(h.open), base + _hours_ms(cutoff), base + _hours_ms(h.close + h.overtime)))
        self._horizon_end = self.windows[-1][2]
        for t in trucks:
            if t.arrive_ms // MS_PER_DAY >= days:
                raise ModelError(f"Truck {t.id} arrives on day {t.arrive_ms // MS_PER_DAY + 1}, but the run covers "
                                 f"{days} day{'s' if days > 1 else ''}.")
        self._check_trucks_can_run()

        self.cal = Calendar()
        self.records: dict[str, TruckRecord] = {}
        self._position: dict[str, int] = {}  # index of the truck's current element in its path (-1 = outside)
        self._location: dict[str, tuple[str, StepRecord | None] | None] = {}  # reservation holding its place
        self._next_area_held: dict[str, str] = {}  # reserve_next_space: area place reserved for after the service
        self._area_count = 0
        self.stall: Stall | None = None
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
        self._dispatched_kg = 0
        self.loads: list[LoadRecord] = []
        self._held: list[ScriptedTruck] = []  # arrived outside admission hours, waiting at the gate
        self._send_away: set[str] = set()  # in service at a hard stop under 'turned_away'; leave when done
        self._ended = False  # past the last day's hard stop
        self._day_events: set[Event] = set()
        for d, (opens, _, stops) in enumerate(self.windows):
            ev_open = self.cal.schedule(opens, CONTROL, lambda c, d=d: self._plant_opens(d), f"day {d + 1}: plant opens")
            ev_stop = self.cal.schedule(stops, CONTROL, lambda c, d=d: self._service_stops(d), f"day {d + 1}: service stops")
            self._day_events |= {ev_open, ev_stop}
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
                    # a loading order may leave the grade open (any grade of the commodity)
                    if truck.grade is None and self.grades.segregated(truck.commodity) and truck.activity != "load":
                        raise ModelError(f"Truck {truck.id} brings {name}, which is graded; give its grade.")
                    if truck.grade is not None and truck.grade not in self.grades.grades[truck.commodity]:
                        raise ModelError(f"Truck {truck.id} has {name} grade {truck.grade}, which is not one of "
                                         "its grades.")
                elif truck.grade is not None:
                    raise ModelError(f"Truck {truck.id} gives a grade for {name}, which has no grades.")
            if "load" in getattr(self.site.sequences, truck.activity) and not self.planner.can_load(truck.commodity):
                name = self.names.get(truck.commodity, truck.commodity)
                raise ModelError(f"No bin for {name} is connected to a load point (truck {truck.id}).")
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

    def _build_path(self, act: str) -> list[str]:
        """The truck's physical path: waiting areas and steps. Without a configured path, an unlimited implicit area
        sits before each step, which reproduces the non-blocking behaviour (listed in the run's assumptions)."""
        explicit = getattr(self.site.truck_paths, act)
        if explicit:
            return list(explicit)
        path: list[str] = []
        for i, step in enumerate(getattr(self.site.sequences, act)):
            area = f"~{act}:{i}"
            self._area_caps[area] = None
            path += [area, step]
        return path

    # ---- event plumbing ----
    def _after_event(self) -> None:
        self.dispatcher.reconsider(self.cal.now)
        for problem in self.ledger.check_invariants(self.cal.now):
            self.violations.append((self.cal.now, problem))
        # Stall: work is waiting and nothing is left that could change it. New arrivals and the daily open/stop
        # events do not count, except that tomorrow's opening resolves waits for a closed plant. After the last
        # day's hard stop, waiting work is reported as unfinished instead.
        waiting = self.dispatcher.waiting_reasons()
        if self.stall is None and not self._ended and waiting and not any(
                e.priority != ARRIVAL and e not in self._day_events for e in self.cal.pending_events()):
            # A wait for a closed plant ends at the next opening, or becomes unfinished work when the run ends.
            closed = any(r.code == "PLANT_CLOSED" for rs in waiting.values() for r in rs)
            day_event_ahead = any(not e.cancelled and not e.done for e in self._day_events)
            # A loading truck short of stock may still be supplied by an unloading truck that has yet to arrive.
            short = any(r.code == "STOCK_SHORT" for rs in waiting.values() for r in rs)
            arrival_ahead = any(e.priority == ARRIVAL for e in self.cal.pending_events())
            if not (closed and day_event_ahead) and not (short and arrival_ahead):
                self.stall = Stall(self.cal.now, waiting)
                self.cal.cancel_all()

    # ---- operating hours (R6) ----
    def _admitting(self, t: int) -> bool:
        return any(opens <= t < cutoff for opens, cutoff, _ in self.windows)

    def _serving(self, t: int) -> bool:
        return any(opens <= t < stops for opens, _, stops in self.windows)

    def _after_cutoff(self, t: int) -> bool:
        """Later than the admission cut-off of the truck's arrival day (as opposed to before opening)."""
        opens, cutoff, _ = self.windows[t // MS_PER_DAY]
        return t >= cutoff

    def _closed(self) -> list[WaitReason]:
        return [WaitReason("PLANT_CLOSED", None, "outside operating hours; waiting for the next opening")]

    def _plant_opens(self, day: int) -> None:
        if day == 0:
            for pit in self.pits.values():
                if pit.lots:
                    self._submit_intake(pit.id)
        held, self._held = self._held, []
        for truck in held:
            self._admit(truck)
        self._after_event()

    def _service_stops(self, day: int) -> None:
        if self.site.end_of_day.unfinished_trucks == "turned_away":
            for rec in self.records.values():
                if rec.admitted is None or rec.departed is not None or rec.turned_away is not None:
                    continue
                loc = self._location.get(rec.truck_id)
                if loc is not None and loc[1] is not None and loc[1].finished is None:
                    self._send_away.add(rec.truck_id)  # in service: completes first (A7)
                else:
                    self._send_away_now(rec.truck_id)
        if day == self.days - 1:
            self._ended = True
        self._after_event()

    def _send_away_now(self, truck_id: str) -> None:
        for rid in self.dispatcher.pending_ids():
            if rid.startswith(f"{truck_id}/"):
                self.dispatcher.withdraw(rid)
        held_area = self._next_area_held.pop(truck_id, None)
        if held_area is not None:
            self.ledger.release(held_area, self.cal.now, "cancelled")
        truck = next(t for t in self.trucks if t.id == truck_id)
        self._leave_location(truck)
        self._awaiting_result.pop(truck_id, None)
        self._send_away.discard(truck_id)
        self.records[truck_id].turned_away = "still on site when service stopped"
        self.records[truck_id].turned_away_at = self.cal.now

    def _leave_or_send_away(self, truck: ScriptedTruck) -> None:
        """After a service: continue, unless the truck must leave and still has steps to do."""
        if truck.id in self._send_away and self._position[truck.id] + 1 < len(self.paths[truck.activity]):
            self._send_away_now(truck.id)
        else:
            self._send_away.discard(truck.id)
            self._advance(truck)

    # ---- trucks: movement along the truck path (R5) ----
    # A truck holds exactly one place at a time: a place in a waiting area, or a station/hopper lane. It gives a
    # place up only when it has the next one, so a truck that finished a service but cannot move on stays on the
    # station and blocks it (A6).
    def _arrive(self, cal: Calendar, truck: ScriptedTruck) -> None:
        rec = self.records[truck.id] = TruckRecord(truck.id, truck.activity, cal.now)  # dict order = arrival order
        if self._admitting(cal.now):
            self._admit(truck)
        elif self.site.end_of_day.late_arrivals == "turned_away" and self._after_cutoff(cal.now):
            rec.turned_away, rec.turned_away_at = "arrived after the admission cut-off", cal.now
        else:
            self._held.append(truck)  # before opening, or late with queue_for_next_day: wait at the gate
        self._after_event()

    def _admit(self, truck: ScriptedTruck) -> None:
        self.records[truck.id].admitted = self.cal.now
        self._position[truck.id] = -1
        self._location[truck.id] = None
        self._advance(truck)

    def _advance(self, truck: ScriptedTruck) -> None:
        """Ask for the next element of the truck's path (a waiting area or a step)."""
        rec = self.records[truck.id]
        path = self.paths[truck.activity]
        nxt = self._position[truck.id] + 1
        if nxt >= len(path):
            self._leave_location(truck)
            rec.departed = self.cal.now
            return
        element = path[nxt]
        if element in self._area_caps:
            held = self._next_area_held.pop(truck.id, None)
            if held is not None:
                self._move_into_area(truck, held)
            else:
                self.dispatcher.submit(f"{truck.id}/enter:{element}", "move", self.cal.now,
                                       lambda now, tr=truck, a=element: self._try_enter(tr, a))
            return
        step_rec = StepRecord(element, self.cal.now)
        rec.steps.append(step_rec)
        if element == "grade":
            self._position[truck.id] = nxt  # the truck stays where it is while its sample is graded
            sample_id = f"S-{truck.id}"
            if sample_id in self._results:
                self._result_reached_truck(truck, step_rec)
            else:
                self._awaiting_result[truck.id] = sample_id
            return
        handler = {"tip": self._try_tip, "load": self._try_load}.get(element, self._try_truck_station)
        attempt = lambda now, tr=truck, sr=step_rec, h=handler: h(tr, sr)  # noqa: E731
        self.dispatcher.submit(f"{truck.id}/{element}", QUEUE_GROUP[element], self.cal.now, attempt)

    def _result_reached_truck(self, truck: ScriptedTruck, step_rec: StepRecord) -> None:
        step_rec.started = step_rec.finished = self.cal.now
        self._advance(truck)

    def _leave_location(self, truck: ScriptedTruck) -> None:
        loc = self._location.get(truck.id)
        if loc is None:
            return
        res_id, step_rec = loc
        self.ledger.release(res_id, self.cal.now, "completed")
        if step_rec is not None:
            step_rec.left = self.cal.now
        self._location[truck.id] = None

    def _move_into_area(self, truck: ScriptedTruck, res_id: str) -> None:
        self._leave_location(truck)
        self._location[truck.id] = (res_id, None)
        self._position[truck.id] += 1
        self._advance(truck)

    def _try_enter(self, truck: ScriptedTruck, area: str) -> list[WaitReason]:
        self._area_count += 1
        res_id = f"{truck.id}/area:{area}#{self._area_count}"
        reasons = self.ledger.try_reserve(res_id, [AreaClaim(area)], self.cal.now)
        if reasons:
            return reasons
        self._move_into_area(truck, res_id)
        return []

    def _reserve_service(self, truck: ScriptedTruck, res_id: str, claims: list,
                         extra: list[tuple[str, list]] | None = None) -> list[WaitReason]:
        """Reserve a service (and any `extra` reservations, e.g. a load-out route) as one transaction. With
        reserve_next_space, a place in the finite area after the service is part of the same transaction, so the
        truck can always move on when the service ends."""
        items = [(res_id, claims)] + list(extra or [])
        path = self.paths[truck.activity]
        after = self._position[truck.id] + 2
        area_res = None
        if (self.site.deadlock_prevention == "reserve_next_space" and after < len(path)
                and self._area_caps.get(path[after]) is not None):
            self._area_count += 1
            area_res = f"{truck.id}/area:{path[after]}#{self._area_count}"
            items.append((area_res, [AreaClaim(path[after])]))
        reasons = self.ledger.try_reserve_many(items, self.cal.now)
        if not reasons and area_res is not None:
            self._next_area_held[truck.id] = area_res
        return reasons

    def _occupy_station(self, truck: ScriptedTruck, res_id: str, step_rec: StepRecord) -> None:
        self._leave_location(truck)
        self._location[truck.id] = (res_id, step_rec)
        self._position[truck.id] += 1

    def _try_lane(self, reservation_id: str, kind: str, step: str) -> tuple[_Unit | None, list[WaitReason]]:
        """A lane for a sample (grading); samples do not occupy truck places."""
        compatible = [u for u in self.units if u.type == kind and u.serves(step)]
        for u in compatible:
            if self.ledger.lane_free(u.resource):
                if self.ledger.try_reserve(reservation_id, [LaneClaim(u.resource)], self.cal.now) == []:
                    return u, []
        ids = sorted({u.equipment_id for u in compatible})
        return None, [WaitReason("EQUIPMENT_BUSY", ",".join(ids), f"{', '.join(ids)} busy")]

    def _try_truck_station(self, truck: ScriptedTruck, step_rec: StepRecord) -> list[WaitReason]:
        if not self._serving(self.cal.now):
            return self._closed()
        res_id = f"{truck.id}/{step_rec.step}"
        compatible = [u for u in self.units if u.type == STATION_TYPE[step_rec.step] and u.serves(step_rec.step)]
        for u in compatible:
            if not self.ledger.lane_free(u.resource):
                continue
            got = self._reserve_service(truck, res_id, [LaneClaim(u.resource)])
            if got:
                return got  # the next area is full: the same for every lane
            self._occupy_station(truck, res_id, step_rec)
            step_rec.unit, step_rec.started = u.resource, self.cal.now
            end = self.cal.now + self.times.duration_ms(truck.id, step_rec.step, u.equipment_id)
            self.cal.schedule(end, RELEASE, lambda c: self._truck_service_done(truck, step_rec),
                              f"{truck.id} finishes {step_rec.step} at {u.equipment_id}")
            return []
        ids = sorted({u.equipment_id for u in compatible})
        return [WaitReason("EQUIPMENT_BUSY", ",".join(ids), f"{', '.join(ids)} busy")]

    def _truck_service_done(self, truck: ScriptedTruck, step_rec: StepRecord) -> None:
        step_rec.finished = self.cal.now  # the truck keeps the lane until it can move on
        if step_rec.step == "sample":
            sample_id = f"S-{truck.id}"
            self.dispatcher.submit(f"{sample_id}/grade", "grade", self.cal.now,
                                   lambda now: self._try_grade(sample_id, truck))
        self._leave_or_send_away(truck)
        self._after_event()

    # ---- samples ----
    def _try_grade(self, sample_id: str, truck: ScriptedTruck) -> list[WaitReason]:
        if not self._serving(self.cal.now):
            return self._closed()
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
        if not self._serving(self.cal.now):
            return self._closed()
        grain, kg, res_id = self._grain(truck), truck.kg, f"{truck.id}/tip"
        reasons: list[WaitReason] = []
        for pit in self._hopper_candidates(truck):
            lane = f"{pit.id}:tip"
            if not self.ledger.lane_free(lane):  # cheap check first; a lane coming free triggers a re-check anyway
                busy = WaitReason("EQUIPMENT_BUSY", lane, f"{lane} busy")
                if busy not in reasons:
                    reasons.append(busy)
                continue
            got = self._reserve_service(truck, res_id, [LaneClaim(lane), PitSpaceClaim(pit.id, grain, kg)])
            if not got:
                self._occupy_station(truck, res_id, step_rec)
                step_rec.unit, step_rec.started = pit.id, self.cal.now
                end = self.cal.now + self.times.duration_ms(truck.id, "tip", pit.id)
                self.cal.schedule(end, RELEASE, lambda c, p=pit: self._tip_done(truck, step_rec, p, res_id),
                                  f"{truck.id} finishes tipping into {pit.id}")
                return []
            reasons.extend(r for r in got if r not in reasons)
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
        self._tipped_kg += truck.kg  # the truck keeps the tipping lane until it can move on
        step_rec.finished = self.cal.now
        if pit.id not in self._intake_active:
            self._submit_intake(pit.id)
        self._leave_or_send_away(truck)
        self._after_event()

    # ---- loading ----
    def _try_load(self, truck: ScriptedTruck, step_rec: StepRecord) -> list[WaitReason]:
        """Reserve, as one transaction: the load point (the truck's place), the load-out route and the truck's
        tonnage of stock in one bin. Route preference: fewest changeover minutes, then shortest route."""
        if not self._serving(self.cal.now):
            return self._closed()
        grade = truck.grade if truck.grade is not None and self.grades.segregated(truck.commodity) else None
        candidates = self.planner.load_candidates(truck.commodity, grade)
        name = self.names.get(truck.commodity, truck.commodity)
        if not candidates:
            return [WaitReason("STOCK_SHORT", None, f"no bin holds {name}" + (f" grade {grade}" if grade else ""))]
        options = []
        for i, path in enumerate(candidates):
            grain = self.bins[path[0]].identity
            changeovers = self._changeovers(path[1:-1], grain)
            options.append((max(changeovers.values(), default=0), len(path), i, path, grain, changeovers))
        options.sort(key=lambda o: o[:3])
        res_id, route_res = f"{truck.id}/load", f"{truck.id}/load-route"
        reasons: list[WaitReason] = []
        for co, _, _, path, grain, changeovers in options:
            lp, bin_id, segments = path[-1], path[0], path[1:-1]
            lane = f"{lp}:load"
            if not self.ledger.lane_free(lane):
                busy = WaitReason("EQUIPMENT_BUSY", lane, f"{lane} busy")
                if busy not in reasons:
                    reasons.append(busy)
                continue
            route = [SegmentClaim(s, grain, tuple(path[k:])) for k, s in enumerate(path) if 0 < k < len(path) - 1]
            route.append(BinOutgoingClaim(bin_id, truck.commodity, truck.kg))
            got = self._reserve_service(truck, res_id, [LaneClaim(lane)], extra=[(route_res, route)])
            if got:
                reasons.extend(r for r in got if r not in reasons)
                continue
            self._occupy_station(truck, res_id, step_rec)
            step_rec.unit, step_rec.started = lp, self.cal.now
            setup = self.times.duration_ms(truck.id, "load", lp)
            rate = min([Fraction(str(self.equipment[lp].rate))] + [Fraction(str(self.equipment[s].rate)) for s in segments])
            flow_start = self.cal.now + setup + co
            end = flow_start + math.ceil(Fraction(truck.kg) * 3600 / rate)
            record = LoadRecord(route_res, truck.id, bin_id, path, truck.kg, self.cal.now, flow_start, changeovers)
            self.loads.append(record)
            self.cal.schedule(end, RELEASE, lambda c: self._load_done(truck, step_rec, record),
                              f"{truck.id} loaded {truck.kg} kg from {bin_id}")
            return []
        return reasons

    def _load_done(self, truck: ScriptedTruck, step_rec: StepRecord, record: LoadRecord) -> None:
        self.bins[record.bin].dispatch(record.id, record.kg)
        self._dispatched_kg += record.kg
        record.finished = step_rec.finished = self.cal.now
        clear = max((m(Decimal(str(self.equipment[s].clear_minutes))) for s in record.path[1:-1]), default=0)
        if clear:
            self.cal.schedule(self.cal.now + clear, RELEASE, lambda c: self._load_route_released(record),
                              f"route clear after {record.id}")
        else:
            self._load_route_released(record, in_event=False)
        self._leave_or_send_away(truck)  # the truck keeps the load point until it can move on
        self._after_event()

    def _load_route_released(self, record: LoadRecord, in_event: bool = True) -> None:
        self.ledger.release(record.id, self.cal.now, "completed")
        record.released = self.cal.now
        if in_event:
            self._after_event()

    # ---- intake transfers ----
    def _submit_intake(self, pit_id: str) -> None:
        self._intake_active.add(pit_id)
        self._transfer_count += 1
        req_id = f"{pit_id}/intake#{self._transfer_count}"
        pit = self.pits[pit_id]
        # Oldest grain first across pits: queue position is the age of the pit's head lot (prototype 'fifo' rule).
        self.dispatcher.submit(req_id, "intake", self.cal.now, lambda now: self._try_intake(pit_id, req_id),
                               order=lambda: pit.lots[0].created if pit.lots else self.cal.now)

    def _try_intake(self, pit_id: str, req_id: str) -> list[WaitReason]:
        if not self.site.end_of_day.transfers_after_close and not self._serving(self.cal.now):
            return self._closed()
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
            if rec.departed is None and rec.turned_away is None:
                s = rec.steps[-1] if rec.steps else StepRecord("arrival", rec.arrived)
                in_service = s.started is not None and s.finished is None and s.unit is not None
                loc = self._location.get(rec.truck_id)
                unfinished.append(UnfinishedTruck(rec.truck_id, s.step, in_service, rec.arrived, s.entered,
                                                  loc[0] if loc else None, rec.admitted is not None))
        closing = sum(b.tonnage_kg for b in self.bins.values()) + sum(p.committed_kg for p in self.pits.values())
        return TruckFlowResult(
            records=list(self.records.values()), unfinished=unfinished, samples=dict(self._results),
            overtaken=self.dispatcher.overtaken(), trace=list(self.cal.log), transfers=list(self.transfers),
            bins={bid: (b.tonnage_kg, b.identity) for bid, b in self.bins.items()},
            pits={pid: p.committed_kg for pid, p in self.pits.items()},
            changeovers={seg: n for seg in self.ledger.segment_ids()
                         if (n := sum(1 for x in [*self.transfers, *self.loads] if seg in x.changeover_segments))},
            material_balance_kg=self._opening_kg + self._tipped_kg - self._dispatched_kg - closing,
            violations=list(self.violations), stall=self.stall, assumptions=list(self.assumptions),
            area_peak={a.id: self.ledger.area_peak[a.id] for a in self.site.truck_areas},
            summary=self._summaries(), received_kg=self._tipped_kg, loads=list(self.loads),
            dispatched_kg=self._dispatched_kg, **self._fairness())

    def _fairness(self) -> dict:
        """Q1 reporting: per-truck waiting, overtakes by later arrivals and completion; per-commodity summaries."""
        end = min(self.cal.now, self._horizon_end)
        order = {tid: i for i, tid in enumerate(self.records)}

        def owner(request_id: str) -> str | None:
            tid = request_id.split("/")[0]
            tid = tid[2:] if tid.startswith("S-") else tid  # a truck's sample in the grading queue
            return tid if tid in order else None

        overtaken = {tid: 0 for tid in order}
        at_hopper = {tid: 0 for tid in order}
        for victim, by in self.dispatcher.overtake_log:
            v, b = owner(victim), owner(by)
            if v is not None and b is not None and order[b] > order[v]:
                overtaken[v] += 1
                if victim.endswith("/tip"):
                    at_hopper[v] += 1
        limit_min, limit_overtakes = self.site.fairness.starvation_wait_minutes, self.site.fairness.starvation_overtakes
        trucks = {t.id: t for t in self.trucks}
        metrics: dict[str, TruckMetrics] = {}
        for tid, rec in self.records.items():
            stop = rec.departed if rec.departed is not None else (rec.turned_away_at if rec.turned_away is not None else end)
            service = 0
            for s in rec.steps:
                if s.step != "grade" and s.unit is not None and s.started is not None:
                    service += (s.finished if s.finished is not None else stop) - s.started
            tip = next((s for s in rec.steps if s.step == "tip"), None)
            hopper = None if tip is None else ((tip.started if tip.started is not None else stop) - tip.entered) / MS_PER_MINUTE
            waiting = (stop - rec.arrived - service) / MS_PER_MINUTE
            starved = waiting >= limit_min or (limit_overtakes is not None and overtaken[tid] >= limit_overtakes)
            truck = trucks[tid]
            status = "turned_away" if rec.turned_away is not None else "completed" if rec.departed is not None else "unfinished"
            entered: dict[str, int] = {}
            for s in rec.steps:
                entered.setdefault(s.step, s.entered)
            metrics[tid] = TruckMetrics(
                truck_id=tid, activity=rec.activity, commodity=truck.commodity, grade=truck.grade,
                arrived=rec.arrived, gate_admitted=rec.admitted, queue_entered=entered,
                hopper_queue_entered=None if tip is None else tip.entered,
                hopper_admitted=None if tip is None else tip.started, departed=rec.departed,
                total_waiting_min=waiting, hopper_wait_min=hopper, overtaken_by_later=overtaken[tid],
                overtaken_at_hopper=at_hopper[tid], status=status, unfinished=status == "unfinished",
                turned_away=status == "turned_away", starved=starved)
        mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
        rank = lambda xs, p: sorted(xs)[max(0, math.ceil(p * len(xs)) - 1)] if xs else None  # noqa: E731 nearest rank
        fairness: dict[str, ActivityFairness] = {}
        for act in ACTIVITY_LABEL:
            ms = [x for x in metrics.values() if x.activity == act]
            if not ms:
                continue
            by: dict[str, CommodityFairness] = {}
            for c in dict.fromkeys(x.commodity or "none" for x in ms):
                group = [x for x in ms if (x.commodity or "none") == c]
                waits = [x.total_waiting_min for x in group]
                hops = [x.hopper_wait_min for x in group if x.hopper_wait_min is not None]
                turn = [(x.departed - x.arrived) / MS_PER_MINUTE for x in group if x.departed is not None]
                over = [x.overtaken_by_later for x in group]
                by[c] = CommodityFairness(
                    len(group), mean(waits), max(waits), mean(hops), max(hops) if hops else None, mean(turn),
                    sum(1 for x in group if x.unfinished),
                    median_total_wait_min=rank(waits, 0.5), p95_total_wait_min=rank(waits, 0.95),
                    median_hopper_wait_min=rank(hops, 0.5), p95_hopper_wait_min=rank(hops, 0.95),
                    mean_overtaken=mean(over), max_overtaken=max(over),
                    max_overtaken_at_hopper=max(x.overtaken_at_hopper for x in group),
                    starved=sum(1 for x in group if x.starved), turned_away=sum(1 for x in group if x.turned_away))
            worst = max(ms, key=lambda x: (x.overtaken_by_later, -order[x.truck_id]))
            fairness[act] = ActivityFairness(by, worst.overtaken_by_later,
                                             worst.truck_id if worst.overtaken_by_later else None,
                                             sum(1 for x in ms if x.starved), limit_min, limit_overtakes)
        return {"truck_metrics": metrics, "fairness": fairness}

    def _summaries(self) -> dict[str, ActivitySummary]:
        """R6: completed, unfinished and turned-away trucks per activity; unfinished are never silently dropped."""
        end = min(self.cal.now, self._horizon_end)  # waiting is measured to the last day's hard stop at most
        out = {}
        for act in ACTIVITY_LABEL:
            recs = [r for r in self.records.values() if r.activity == act]
            if not recs and not any(t.activity == act for t in self.trucks):
                continue
            done = sorted((r.departed - r.arrived) / MS_PER_MINUTE for r in recs if r.departed is not None)
            waiting = [(end - r.arrived) / MS_PER_MINUTE for r in recs
                       if r.departed is None and r.turned_away is None]
            pct = lambda p: done[max(0, math.ceil(p * len(done)) - 1)] if done else None  # noqa: E731 nearest rank
            both = done + waiting
            out[act] = ActivitySummary(
                completed=len(done), unfinished=len(waiting),
                turned_away=sum(1 for r in recs if r.turned_away is not None),
                mean_turnaround_min=sum(done) / len(done) if done else None,
                median_turnaround_min=pct(0.5), p90_turnaround_min=pct(0.9),
                max_turnaround_min=done[-1] if done else None,
                unfinished_waiting_min=waiting,
                mean_turnaround_incl_unfinished_min=sum(both) / len(both) if both else None)
        return out
