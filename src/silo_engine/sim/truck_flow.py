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
import dataclasses
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction

from ..config.grades import GradePolicy
from ..config.routes import build_routes
from ..config.rules_validation import validate_rules
from ..config.schema import ReconciliationSettings, SiteConfig
from ..domain.book import BookLedger
from ..domain.changeover import ChangeoverMatrix
from ..domain.quantities import tonnes_to_kg
from ..domain.storage import GradedCommodity, StorageBin
from ..inputs.scripted import ScriptedTruck, schedule_arrivals
from .calendar import ARRIVAL, CONTROL, RELEASE, Calendar, Event
from .dispatcher import Dispatcher, DispatcherError, WaitReason
from .ledger import (AreaClaim, BinIncomingClaim, BinOutgoingClaim, LaneClaim, PitSpaceClaim, ReservationLedger,
                     SegmentClaim)
from .pit import Lot, Pit
from .queue_policy import DEFAULT_POLICY, UnsupportedPrototypePolicy, from_prototype
from .routing import RoutePlanner
from .service_times import ServiceTimes
from .time import MS_PER_DAY, MS_PER_MINUTE, hm, m

STATION_TYPE = {"sample": "sampler", "weigh_in": "weighbridge", "weigh_out": "weighbridge", "pass": "sampler"}
QUEUE_GROUP = {"sample": "sample", "pass": "sample", "grade": "grade", "weigh_in": "weigh", "weigh_out": "weigh",
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
    interruptions: list[list[int | None]] = field(default_factory=list)  # [suspended, resumed or None] (step 17)


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
    interruptions: list[list[int | None]] = field(default_factory=list)  # [suspended, resumed or None] (step 17)


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
    # Domain decisions of 2026-10-23 (docs/QUEUE_POLICY_DESIGN.md §4); the fields above keep their definitions.
    arrival_seq: int = 0  # gate arrival order (0 = first)
    queue_seq: dict[str, int] = field(default_factory=dict)  # step -> queue-entry order (dispatcher submission number)
    overtaken_in_queue: int = 0  # queue-stage count: later queue entrants that started first (gate order ignored)
    hopper_admitted_ahead_by_later_arrivals: int = 0  # gate-arrival fairness: later gate arrivals that tipped first
    overtaken_feasible: int = 0  # part of overtaken_by_later on equipment this truck is configured to be able to use
    overtaken_infeasible: int = 0  # the rest (e.g. a hopper that does not take this commodity)
    pre_opening_wait_min: float = 0  # held at the gate until it opened (before opening, or after the cut-off)
    operational_wait_min: float = 0  # total_waiting_min - pre_opening_wait_min
    wait_censored: bool = False  # right-censored at the end of the run: the waiting time is a lower bound


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
    # Right-censoring (2026-10-23): completed trucks only, and censored (unfinished) trucks apart. Turned-away
    # trucks are in neither group.
    completed_mean_wait_min: float | None = None
    completed_median_wait_min: float | None = None
    completed_p95_wait_min: float | None = None
    completed_max_wait_min: float | None = None
    censored: int = 0
    censored_mean_wait_min: float | None = None  # lower bound
    censored_max_wait_min: float | None = None  # lower bound
    mean_pre_opening_wait_min: float | None = None
    mean_operational_wait_min: float | None = None
    mean_admitted_ahead_by_later_arrivals: float | None = None
    max_admitted_ahead_by_later_arrivals: int = 0
    overtaken_feasible: int = 0  # totals over the commodity's trucks
    overtaken_infeasible: int = 0


@dataclass(frozen=True)
class ActivityFairness:
    by_commodity: dict[str, CommodityFairness]  # commodity id ("none" for weighbridge-only trucks)
    max_overtaken: int
    most_overtaken_truck: str | None
    starved: int
    starvation_wait_minutes: float
    starvation_overtakes: int | None


@dataclass(frozen=True)
class LotFlow:
    """One grain lot from tipping to storage (docs/MATERIAL_FLOW_AUDIT.md). A truck's unloading is complete when it
    finishes tipping (`tipped_at`); its grain is in storage only when every kilogram has reached a bin (`stored_at`).
    Opening pit contents are lots without a truck (tipped_at None)."""
    lot_id: str
    truck_id: str | None
    pit: str
    commodity: str
    grade: str | None
    kg: int
    tipped_at: int | None
    first_transfer_at: int | None  # route reserved for the first part of the lot
    stored_at: int | None  # the last kilogram reached a bin (None: not all stored when the run ended)
    stored_kg: int
    in_transit_kg: int  # in transfers still running at the end (counted in the pit until they finish)
    in_pit_kg: int  # not yet sent
    bins: tuple[str, ...]  # bins it went to, in order (more than one when a bin filled)
    on_route_kg: int = 0  # part of in_transit_kg that has left the pit but not reached the bin (whole kg, rounded down)


@dataclass(frozen=True)
class LossRecord:
    """An applied process loss (step 18). Bins are aggregates: a loss is not attributed to truck lots."""
    id: str
    time: int
    bin: str
    commodity: str | None
    kg: int
    cause: str  # moisture losses are generic mass losses: water content is not modelled
    posted: bool


@dataclass(frozen=True)
class Observation:
    """A stock measurement (S7): recorded beside physical and book stock; changes neither."""
    id: str
    time: int
    bin: str
    observed_kg: int
    physical_kg: int
    book_kg: int
    minus_book_kg: int  # observed - book
    minus_physical_kg: int  # observed - physical (simulation only: the model knows the physical truth)
    tolerance_kg: int | None
    flagged: bool  # |observed - book| > tolerance; False when no tolerance is configured


@dataclass(frozen=True)
class StockLogEntry:
    id: str
    time: int
    kind: str
    bin: str
    applied: bool
    refused_because: str | None
    delta_physical_kg: int
    delta_book_kg: int
    basis: str | None = None  # book corrections
    posted: bool | None = None  # process losses


@dataclass(frozen=True)
class BinReconciliation:
    """D = book - physical, explained by its components; `unexplained_kg` is reported, never absorbed."""
    physical_kg: int
    book_kg: int
    difference_kg: int
    opening_difference_kg: int
    administrative_kg: int
    survey_based_kg: int
    unposted_loss_kg: int
    unexplained_kg: int


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
    queue_policies: dict[str, str] = field(default_factory=dict)  # queue group -> policy used
    # Sampler access: per truck (requires_sampling, pass_throughs, blocked_behind_ms, bypass_used); per configured
    # area (time_average, peak, single_file); exits from single-file areas (time, area, truck, via_bypass).
    truck_access: dict[str, dict] = field(default_factory=dict)
    area_occupancy: dict[str, dict] = field(default_factory=dict)
    single_file_exits: list[tuple] = field(default_factory=list)
    single_file_log: list[tuple] = field(default_factory=list)  # (time, area, truck, "enter"/"exit", via bypass)
    lots: dict[str, LotFlow] = field(default_factory=dict)  # lot id -> tipping-to-storage record
    # Step 18: process losses, book inventory per bin, observations, stock event log, reconciliation per bin + "site".
    losses: list[LossRecord] = field(default_factory=list)
    book: dict[str, int] = field(default_factory=dict)
    observations: list[Observation] = field(default_factory=list)
    stock_log: list[StockLogEntry] = field(default_factory=list)
    reconciliation: dict[str, BinReconciliation] = field(default_factory=dict)
    policy_source: str = ""  # "argument", "site" or "default"


def _hours_ms(hours: float) -> int:
    return m(Decimal(str(hours)) * 60)


def _kg_per_ms(rate_tph: Fraction) -> Fraction:
    return rate_tph * 1000 / 3_600_000


class TruckFlowModel:
    def __init__(self, site: SiteConfig, trucks: list[ScriptedTruck], times: ServiceTimes,
                 policy: str | dict[str, str] | None = None, days: int = 1,
                 reconciliation_tolerance: dict | None = None):
        if days < 1:
            raise ModelError("A run covers at least one day.")
        self.site = site
        self.days = days
        self.trucks = trucks
        self.times = times
        self.names = {c.id: c.name for c in site.commodities}
        groups = sorted(set(QUEUE_GROUP.values()))
        # Precedence: the run's argument, then the site's queue_policies, then the unchanged default.
        if policy is not None:
            self.policy_source = "argument"
            policies = {g: policy for g in groups} if isinstance(policy, str) else dict(policy)
        elif site.queue_policies is not None:
            self.policy_source = "site"
            policies = {g: site.queue_policies.groups.get(g, site.queue_policies.default) for g in groups}
        else:
            self.policy_source = "default"
            policies = {g: DEFAULT_POLICY for g in groups}
        self.queue_policies = {g: p if isinstance(p, str) else p.name for g, p in policies.items()}
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
        self._lots_seen: dict[str, tuple] = {}  # lot id -> (truck, pit, grain, kg, tipped at); reporting only
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
        note = self._prototype_policy_note(site)
        if note:
            self.assumptions.append(note)
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
        self._arrival_seq: dict[str, int] = {}  # gate arrival order (simultaneous arrivals: script order)
        self._queue_seq: dict[str, dict[str, int]] = {}  # truck -> step -> submission sequence (queue-entry order)
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
        # Sampler access (docs/SAMPLER_ACCESS_DESIGN.md).
        self._single_file = {a.id for a in site.truck_areas if a.single_file}
        self._area_order: dict[str, list[str]] = {a: [] for a in self._single_file}
        self._in_area: dict[str, str] = {}
        self._behind_since: dict[str, int] = {}  # truck -> when it started waiting behind another in a single-file area
        self._access: dict[str, dict] = {}
        self._area_occ = {a.id: [0, None, 0, 0] for a in site.truck_areas}  # count, last change, integral, peak
        self._sf_exits: list[tuple] = []
        self._sf_log: list[tuple] = []  # chronological single-file entries and exits
        self._bypass = {(b.activity, b.from_): b.to for b in site.truck_bypasses}
        self._target: dict[str, int] = {}  # truck -> index of the path element it is about to occupy
        self._via_bypass: set[str] = set()
        self._colocated = {e.id: (e.located_at, e.located_lanes) for e in site.equipment if e.type == "sampler" and e.located_at}
        self._bay_held: dict[str, tuple] = {}  # truck -> (bay unit, bay reservation id) after co-located sampling
        self._crew_res: dict[str, str] = {}
        self._truck_by_id = {t.id: t for t in trucks}
        # Step 17: suspended transfers and loads (route held), and each running load's completion.
        self._suspended: dict[str, TransferRecord | LoadRecord] = {}
        self._load_end: dict[str, tuple[Event, int]] = {}  # load id -> (completion event, end time)
        self._load_left: dict[str, int] = {}  # suspended load id -> ms of its clock still to run
        self._load_owner: dict[str, tuple[ScriptedTruck, StepRecord]] = {}
        self.transfers: list[TransferRecord] = []
        self.violations: list[tuple[int, str]] = []
        self._opening_kg = sum(b.tonnage_kg for b in self.bins.values()) + sum(p.committed_kg for p in self.pits.values())
        # Step 18: book inventory (independent of the bins), observations, losses.
        self._opening_bins = {bid: b.tonnage_kg for bid, b in self.bins.items()}
        book0 = {o.bin: tonnes_to_kg(o.tonnes) if o.tonnes else 0 for o in site.opening_book}
        self.book = BookLedger({bid: book0.get(bid, kg) for bid, kg in self._opening_bins.items()})
        self._tolerance = ReconciliationSettings(**reconciliation_tolerance) if reconciliation_tolerance is not None \
            else site.reconciliation
        self._observations: dict[str, Observation] = {}
        self.losses: list[LossRecord] = []
        self.stock_log: list[StockLogEntry] = []
        self._lost_kg = 0
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
        for i, ev in enumerate(site.stock_events, start=1):  # validated by validate_rules
            when = (ev.day - 1) * MS_PER_DAY + hm(ev.time)
            self.cal.schedule(when, CONTROL, lambda c, ev=ev, i=i: self._stock_event(ev, i), f"stock event {i}: {ev.kind}")
        if any(ev.kind == "process_loss" and ev.cause == "moisture" for ev in site.stock_events):
            self.assumptions.append("Moisture losses are generic physical mass losses: water content and drying are "
                                    "not modelled, and grade and identity are unchanged.")
        for o in site.outages:  # validated by validate_rules
            start = (o.day - 1) * MS_PER_DAY + hm(o.start)
            self.cal.schedule(start, CONTROL, lambda c, e=o.equipment: self._equipment_down(e), f"{o.equipment} unavailable")
            if o.end is not None:
                end = (o.day - 1) * MS_PER_DAY + hm(o.end)
                self.cal.schedule(end, CONTROL, lambda c, e=o.equipment: self._equipment_up(e), f"{o.equipment} available")

    # ---- construction ----
    def _prototype_policy_note(self, site: SiteConfig) -> str | None:
        """The prototype-format `policies` field is not applied (docs/QUEUE_POLICY_DESIGN.md §9). Say so when a
        configuration sets it and it differs from the queue policies this run actually uses."""
        if "policies" not in site.model_fields_set:
            return None
        given = ", ".join(f"{k}='{v}'" for k, v in site.policies.model_dump().items())
        used = f"this run uses {self.queue_policies} ({self.policy_source})"
        try:
            if from_prototype(site.policies.model_dump()) == self.queue_policies:
                return None
            return f"The configuration's prototype policies ({given}) are not applied; {used}."
        except UnsupportedPrototypePolicy as e:
            return f"The configuration's prototype policies ({given}) are not applied: {e} Instead {used}."

    def _make_bin(self, e) -> StorageBin:
        opening_kg = tonnes_to_kg(e.inv) if e.inv else 0
        opening = self.grades.grain(e.inv_commodity, e.inv_grade) if opening_kg else None
        return StorageBin(e.id, tonnes_to_kg(e.cap_t), self.grades.bin_accepts(e), self.mixing, opening_kg, opening)

    def _make_pit(self, e) -> Pit:
        lots = []
        if e.level0:
            grain = self.grades.grain(e.level_commodity, e.level_grade)
            lots.append(Lot(f"L0-{e.id}", None, grain, tonnes_to_kg(e.level0), 0))
            self._lots_seen[f"L0-{e.id}"] = (None, e.id, grain, tonnes_to_kg(e.level0), None)
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
        self._resume_suspended()
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
        self._arrival_seq[truck.id] = len(self.records) - 1
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
        pos = self._position[truck.id]
        nxt = pos + 1
        via_bypass = False
        if not self._needs_sampling(truck):
            to = self._bypass.get((truck.activity, path[pos])) if pos >= 0 else None
            if to is not None and path.index(to) > nxt:
                nxt, via_bypass = path.index(to), True
            # services this truck does not need are skipped; a separate sampler bay on the path is still traversed
            while nxt < len(path) and (path[nxt] == "grade" or (path[nxt] == "sample" and self._colocated)):
                nxt += 1
        if nxt >= len(path):
            self._leave_location(truck)
            rec.departed = self.cal.now
            return
        self._target[truck.id] = nxt
        if via_bypass:
            self._via_bypass.add(truck.id)
            self._access_of(truck)["bypass_used"] = True
        element = path[nxt]
        if element in self._area_caps:
            held = self._next_area_held.pop(truck.id, None)
            if held is not None:
                self._move_into_area(truck, held)
            else:
                self._submit_for(truck, f"enter:{element}", f"{truck.id}/enter:{element}", "move",
                                 self._guarded(truck, lambda now, tr=truck, a=element: self._try_enter(tr, a)))
            return
        if element == "sample" and not self._needs_sampling(truck):
            element = "pass"  # physically traverses a separate sampler bay: occupies it without sampling service
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
        if element == "sample" and self._colocated:
            handler = self._try_colocated_sample
        attempt = lambda now, tr=truck, sr=step_rec, h=handler: h(tr, sr)  # noqa: E731
        self._submit_for(truck, element, f"{truck.id}/{element}", QUEUE_GROUP[element], self._guarded(truck, attempt))

    # ---- sampler access (docs/SAMPLER_ACCESS_DESIGN.md) ----
    def _needs_sampling(self, truck: ScriptedTruck) -> bool:
        if truck.requires_sampling is not None:
            return truck.requires_sampling
        return "sample" in getattr(self.site.sequences, truck.activity)

    def _access_of(self, truck: ScriptedTruck) -> dict:
        return self._access.setdefault(truck.id, {"requires_sampling": self._needs_sampling(truck), "pass_throughs": 0,
                                                  "blocked_behind_ms": 0, "bypass_used": False})

    def _guarded(self, truck: ScriptedTruck, attempt):
        """Physical order: a truck in a single-file area may move on only from the front, unless it leaves through
        a declared bypass. This is a feasibility rule of the layout; no queue policy can override it."""
        area = self._in_area.get(truck.id)
        if area not in self._single_file or truck.id in self._via_bypass:
            return attempt

        def guarded(now):
            order = self._area_order[area]
            if order and order[0] != truck.id:
                return [WaitReason("PHYSICAL_QUEUE_ORDER", area, f"behind {order[0]} in single-file {area}")]
            return attempt(now)
        return guarded

    def _area_change(self, area: str, delta: int) -> None:
        occ = self._area_occ.get(area)
        if occ is None:
            return
        now = self.cal.now
        if occ[1] is not None:
            occ[2] += occ[0] * (now - occ[1])
        occ[0] += delta
        occ[1] = now
        occ[3] = max(occ[3], occ[0])

    def _enter_area(self, truck: ScriptedTruck, area: str) -> None:
        self._in_area[truck.id] = area
        self._area_change(area, +1)
        if area in self._single_file:
            order = self._area_order[area]
            order.append(truck.id)
            self._sf_log.append((self.cal.now, area, truck.id, "enter", False))
            if order[0] != truck.id and not (not self._needs_sampling(truck) and (truck.activity, area) in self._bypass):
                self._behind_since[truck.id] = self.cal.now

    def _exit_area(self, truck: ScriptedTruck) -> None:
        area = self._in_area.pop(truck.id, None)
        if area is None:
            return
        self._area_change(area, -1)
        if area in self._single_file:
            order = self._area_order[area]
            was_front = order and order[0] == truck.id
            self._sf_exits.append((self.cal.now, area, truck.id, truck.id in self._via_bypass))
            self._sf_log.append((self.cal.now, area, truck.id, "exit", truck.id in self._via_bypass))
            order.remove(truck.id)
            start = self._behind_since.pop(truck.id, None)
            if start is not None:  # left from behind (bypass): stop counting
                self._access_of(truck)["blocked_behind_ms"] += self.cal.now - start
            if was_front and order and order[0] in self._behind_since:
                front = self._truck_by_id[order[0]]
                self._access_of(front)["blocked_behind_ms"] += self.cal.now - self._behind_since.pop(front.id)
        self._via_bypass.discard(truck.id)

    def _try_colocated_sample(self, truck: ScriptedTruck, step_rec: StepRecord) -> list[WaitReason]:
        """Sampling at a weighbridge bay: the bay (the truck's position) and a sampling unit are reserved together;
        the unit is released when sampling ends, the bay is kept for weighing in."""
        if not self._serving(self.cal.now):
            return self._closed()
        wb, lanes = next(iter(self._colocated.values()))
        bays = [u for u in self.units if u.equipment_id == wb and (lanes is None or u.lane in lanes)]
        crews = [u for u in self.units if u.type == "sampler"]
        bay = next((u for u in bays if self.ledger.lane_free(u.resource)), None)
        crew = next((u for u in crews if self.ledger.lane_free(u.resource)), None)
        if bay is None or crew is None:
            busy = [u.resource for u in (bays if bay is None else crews)]
            return [WaitReason("EQUIPMENT_BUSY", ",".join(busy), f"{', '.join(busy)} busy")]
        bay_res, crew_res = f"{truck.id}/sample-bay", f"{truck.id}/sample-unit"
        reasons = self.ledger.try_reserve_many([(bay_res, [LaneClaim(bay.resource)]), (crew_res, [LaneClaim(crew.resource)])],
                                               self.cal.now)
        if reasons:
            return reasons
        self._occupy_station(truck, bay_res, step_rec)
        self._bay_held[truck.id] = (bay, bay_res)
        self._crew_res[truck.id] = crew_res
        step_rec.unit, step_rec.started = bay.resource, self.cal.now
        end = self.cal.now + self.times.duration_ms(truck.id, "sample", crew.equipment_id)
        self.cal.schedule(end, RELEASE, lambda c: self._colocated_sample_done(truck, step_rec),
                          f"{truck.id} sampled at {bay.resource}")
        return []

    def _colocated_sample_done(self, truck: ScriptedTruck, step_rec: StepRecord) -> None:
        self.ledger.release(self._crew_res.pop(truck.id), self.cal.now, "completed")
        self._truck_service_done(truck, step_rec)

    def _weigh_on_held_bay(self, truck: ScriptedTruck, step_rec: StepRecord) -> list[WaitReason]:
        """Weighing in on the bay the truck already holds after co-located sampling (no new bay reservation)."""
        bay, bay_res = self._bay_held[truck.id]
        path = self.paths[truck.activity]
        after = self._target.get(truck.id, self._position[truck.id] + 1) + 1
        if (self.site.deadlock_prevention == "reserve_next_space" and after < len(path)
                and self._area_caps.get(path[after]) is not None):
            self._area_count += 1
            area_res = f"{truck.id}/area:{path[after]}#{self._area_count}"
            reasons = self.ledger.try_reserve(area_res, [AreaClaim(path[after])], self.cal.now)
            if reasons:
                return reasons
            self._next_area_held[truck.id] = area_res
        del self._bay_held[truck.id]
        prev = self._location[truck.id][1]
        if prev is not None:
            prev.left = self.cal.now
        self._location[truck.id] = (bay_res, step_rec)
        self._position[truck.id] = self._target.pop(truck.id, self._position[truck.id] + 1)
        step_rec.unit, step_rec.started = bay.resource, self.cal.now
        end = self.cal.now + self.times.duration_ms(truck.id, "weigh_in", bay.equipment_id)
        self.cal.schedule(end, RELEASE, lambda c: self._truck_service_done(truck, step_rec),
                          f"{truck.id} finishes weigh_in at {bay.equipment_id}")
        return []

    def _submit_for(self, truck: ScriptedTruck, step: str, request_id: str, group: str, attempt) -> None:
        """Queue a truck's request; record its queue-entry order and show the policy read-only truck facts."""
        seq = self.dispatcher.submit(request_id, group, self.cal.now, attempt, info={
            "truck_id": truck.id, "arrival_seq": self._arrival_seq[truck.id], "activity": truck.activity,
            "commodity": truck.commodity, "grade": truck.grade, "step": step})
        self._queue_seq.setdefault(truck.id, {}).setdefault(step, seq)

    def _result_reached_truck(self, truck: ScriptedTruck, step_rec: StepRecord) -> None:
        step_rec.started = step_rec.finished = self.cal.now
        self._advance(truck)

    def _leave_location(self, truck: ScriptedTruck) -> None:
        loc = self._location.get(truck.id)
        if loc is None:
            return
        self._exit_area(truck)
        res_id, step_rec = loc
        self.ledger.release(res_id, self.cal.now, "completed")
        if step_rec is not None:
            step_rec.left = self.cal.now
        self._location[truck.id] = None

    def _move_into_area(self, truck: ScriptedTruck, res_id: str) -> None:
        self._leave_location(truck)
        self._location[truck.id] = (res_id, None)
        area = self.paths[truck.activity][self._target.get(truck.id, self._position[truck.id] + 1)]
        self._position[truck.id] = self._target.pop(truck.id, self._position[truck.id] + 1)
        self._enter_area(truck, area)
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
        after = self._target.get(truck.id, self._position[truck.id] + 1) + 1
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
        self._position[truck.id] = self._target.pop(truck.id, self._position[truck.id] + 1)

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
        if step_rec.step == "weigh_in" and truck.id in self._bay_held:
            return self._weigh_on_held_bay(truck, step_rec)
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
            if step_rec.step == "pass":
                self._access_of(truck)["pass_throughs"] += 1
            end = self.cal.now + self.times.duration_ms(truck.id, step_rec.step, u.equipment_id)
            self.cal.schedule(end, RELEASE, lambda c: self._truck_service_done(truck, step_rec),
                              f"{truck.id} finishes {step_rec.step} at {u.equipment_id}")
            return []
        ids = sorted({u.equipment_id for u in compatible})
        return [WaitReason("EQUIPMENT_BUSY", ",".join(ids), f"{', '.join(ids)} busy")]

    def _truck_service_done(self, truck: ScriptedTruck, step_rec: StepRecord) -> None:
        step_rec.finished = self.cal.now  # the truck keeps the lane until it can move on
        if step_rec.step == "sample" and "grade" in getattr(self.site.sequences, truck.activity):
            sample_id = f"S-{truck.id}"
            self._submit_for(truck, "grade", f"{sample_id}/grade", "grade", lambda now: self._try_grade(sample_id, truck))
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
        self._lots_seen[f"L-{truck.id}"] = (truck.id, pit.id, self._grain(truck), truck.kg, self.cal.now)
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
            self._schedule_load_end(record, truck, step_rec, end)
            return []
        return reasons

    def _schedule_load_end(self, record: LoadRecord, truck: ScriptedTruck, step_rec: StepRecord, end: int) -> None:
        ev = self.cal.schedule(end, RELEASE, lambda c: self._load_done(truck, step_rec, record),
                               f"{truck.id} loaded {truck.kg} kg from {record.bin}")
        self._load_end[record.id] = (ev, end)
        self._load_owner[record.id] = (truck, step_rec)

    def _load_done(self, truck: ScriptedTruck, step_rec: StepRecord, record: LoadRecord) -> None:
        self._load_end.pop(record.id, None)
        self.bins[record.bin].dispatch(record.id, record.kg)
        self.book.post(self.cal.now, record.bin, -record.kg, record.id)
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
        if record.id in self._suspended:  # the route went down during the changeover: flow starts on resume
            return
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
        self.book.post(self.cal.now, b.id, record.kg, record.id)
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

    # ---- stock events (step 18, docs/STOCK_ADJUSTMENTS.md) ----
    def _stock_event(self, ev, i: int) -> None:
        now, b = self.cal.now, self.bins[ev.bin]
        eid = ev.id or f"stock-{i}"
        log = lambda applied, why=None, dp=0, dr=0: self.stock_log.append(StockLogEntry(  # noqa: E731
            eid, now, ev.kind, ev.bin, applied, why, dp, dr, ev.basis, ev.posted if ev.kind == "process_loss" else None))
        if ev.kind == "process_loss":
            kg = tonnes_to_kg(ev.tonnes)
            refused = b.check_loss(kg, ev.commodity)
            if refused:
                log(False, "; ".join(r.detail for r in refused.reasons) + " (only uncommitted stock can be lost)")
            else:
                commodity = b.identity.commodity if b.identity else None
                b.remove_loss(kg, ev.commodity)
                self._lost_kg += kg
                self.losses.append(LossRecord(eid, now, ev.bin, commodity, kg, ev.cause, ev.posted))
                if ev.posted:
                    self.book.post(now, ev.bin, -kg, eid)
                else:
                    self.book.explain(ev.bin, "unposted_loss", kg)
                log(True, None, -kg, -kg if ev.posted else 0)
        elif ev.kind == "stock_measurement":
            observed, physical, book = tonnes_to_kg(ev.observed_tonnes) if ev.observed_tonnes else 0, b.tonnage_kg, \
                self.book.balance[ev.bin]
            tol = self._tolerance_kg(book)
            self._observations[eid] = Observation(eid, now, ev.bin, observed, physical, book, observed - book,
                                                  observed - physical, tol,
                                                  tol is not None and abs(observed - book) > tol)
            log(True)
        else:
            book = self.book.balance[ev.bin]
            if ev.basis == "administrative":
                delta = (1 if ev.tonnes > 0 else -1) * tonnes_to_kg(abs(ev.tonnes))
            elif ev.observation in self._observations:
                delta = self._observations[ev.observation].observed_kg - book
            else:
                log(False, f"observation {ev.observation} not yet made")
                self._after_event()
                return
            if book + delta < 0:
                log(False, f"the book for {ev.bin} would become negative ({book + delta} kg)")
            else:
                self.book.post(now, ev.bin, delta, eid)
                self.book.explain(ev.bin, "administrative" if ev.basis == "administrative" else "survey_based", delta)
                log(True, None, 0, delta)
        self._after_event()

    def _tolerance_kg(self, book_kg: int) -> int | None:
        t = self._tolerance
        options = ([round(t.tolerance_t * 1000)] if t.tolerance_t is not None else []) + \
                  ([round(t.tolerance_fraction * abs(book_kg))] if t.tolerance_fraction is not None else [])
        return max(options) if options else None

    def _reconciliation(self) -> dict[str, BinReconciliation]:
        out = {}
        for bid, b in self.bins.items():
            p, r, e = b.tonnage_kg, self.book.balance[bid], self.book.explained[bid]
            opening = self.book.opening[bid] - self._opening_bins[bid]
            d = r - p
            out[bid] = BinReconciliation(p, r, d, opening, e["administrative"], e["survey_based"], e["unposted_loss"],
                                         d - opening - e["administrative"] - e["survey_based"] - e["unposted_loss"])
        # Site: bins plus pits (pits have no book of their own: book = physical there).
        pits = sum(p.committed_kg for p in self.pits.values())
        tot = lambda f: sum(getattr(x, f) for x in out.values())  # noqa: E731
        out["site"] = BinReconciliation(tot("physical_kg") + pits, tot("book_kg") + pits, tot("difference_kg"),
                                        tot("opening_difference_kg"), tot("administrative_kg"), tot("survey_based_kg"),
                                        tot("unposted_loss_kg"), tot("unexplained_kg"))
        return out

    # ---- equipment outages (step 17, docs/INTERRUPTED_TRANSFERS.md) ----
    def _equipment_down(self, equipment: str) -> None:
        """Suspend every active transfer and load whose route contains the equipment; they keep their reservations."""
        self.ledger.down.add(equipment)
        now = self.cal.now
        for rec in [*self.transfers, *self.loads]:
            if rec.finished is not None or rec.id in self._suspended or equipment not in rec.path[1:-1]:
                continue
            rec.interruptions.append([now, None])
            self._suspended[rec.id] = rec
            if isinstance(rec, TransferRecord):
                pit = self.pits[rec.pit]
                if rec.id in self._flowing:
                    del self._flowing[rec.id]
                    pit.set_rate(now, Fraction(0))
                    self.cal.cancel(self._completion.pop(rec.id))
            else:
                ev, end = self._load_end.pop(rec.id)
                self.cal.cancel(ev)
                self._load_left[rec.id] = end - now
        self._recompute_rates()  # streams still flowing on shared segments take the capacity
        self._after_event()

    def _equipment_up(self, equipment: str) -> None:
        self.ledger.down.discard(equipment)
        self._resume_suspended()
        self._after_event()

    def _resume_suspended(self) -> None:
        """Resume the same transfers and loads once no equipment on their route is unavailable. A transfer resumes
        only when transfers may run (open, or transfers continue after close); a load always may (A7)."""
        now = self.cal.now
        resumed = False
        for rec in list(self._suspended.values()):
            if any(s in self.ledger.down for s in rec.path[1:-1]):
                continue
            stopped = rec.interruptions[-1][0]
            if isinstance(rec, TransferRecord):
                if not self.site.end_of_day.transfers_after_close and not self._serving(now):
                    continue
                del self._suspended[rec.id]
                rec.interruptions[-1][1] = now
                if rec.flow_started <= stopped:  # it was flowing: continue from where it stopped
                    self._flowing[rec.id] = rec
                    resumed = True
                elif rec.flow_started <= now:  # the changeover ended during the stoppage (I3): flow starts now
                    rec.flow_started = now
                    self._flowing[rec.id] = rec
                    resumed = True
                # otherwise the changeover is still running and its scheduled event starts the flow
            else:
                del self._suspended[rec.id]
                rec.interruptions[-1][1] = now
                if rec.flow_started > stopped:  # paused during setup or changeover (I4): flow starts later too
                    rec.flow_started += now - stopped
                truck, step_rec = self._load_owner[rec.id]
                self._schedule_load_end(rec, truck, step_rec, now + self._load_left.pop(rec.id))
        if resumed:
            self._recompute_rates()

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
            material_balance_kg=self._opening_kg + self._tipped_kg - self._dispatched_kg - self._lost_kg - closing,
            violations=list(self.violations), stall=self.stall, assumptions=list(self.assumptions),
            area_peak={a.id: self.ledger.area_peak[a.id] for a in self.site.truck_areas},
            summary=self._summaries(), received_kg=self._tipped_kg, loads=list(self.loads),
            dispatched_kg=self._dispatched_kg, queue_policies=dict(self.queue_policies),
            policy_source=self.policy_source, lots=self._lot_flows(), losses=list(self.losses),
            truck_access=self._access_report(), area_occupancy=self._occupancy_report(),
            single_file_exits=list(self._sf_exits), single_file_log=list(self._sf_log),
            book=dict(self.book.balance), observations=sorted(self._observations.values(), key=lambda o: o.time),
            stock_log=list(self.stock_log), reconciliation=self._reconciliation(), **self._fairness())

    def _access_report(self) -> dict[str, dict]:
        now = min(self.cal.now, self._horizon_end)
        out = {}
        for t in self.trucks:
            if t.id not in self.records:
                continue
            a = dict(self._access_of(t))
            if t.id in self._behind_since:  # still waiting behind another truck at the end
                a["blocked_behind_ms"] += max(0, now - self._behind_since[t.id])
            out[t.id] = a
        return out

    def _occupancy_report(self) -> dict[str, dict]:
        start = self.windows[0][0]
        end = max(start + 1, min(self.cal.now, self._horizon_end))
        out = {}
        for area, (count, last, integral, peak) in self._area_occ.items():
            total = integral + (count * (end - last) if last is not None else 0)
            out[area] = {"time_average": total / (end - start), "peak": peak, "single_file": area in self._single_file}
        return out

    def _lot_flows(self) -> dict[str, LotFlow]:
        out = {}
        for lot_id, (truck_id, pit_id, grain, kg, tipped) in self._lots_seen.items():
            parts = [x for x in self.transfers if x.lot_id == lot_id]
            stored = sum(x.kg for x in parts if x.finished is not None)
            moving = sum(x.kg for x in parts if x.finished is None)
            pit = self.pits[pit_id]
            running = [x for x in parts if x.finished is None]
            on_route = math.floor(pit.drained_at(self.cal.now)) if running and pit.draining is not None else 0
            out[lot_id] = LotFlow(lot_id, truck_id, pit_id, grain.commodity, grain.grade, kg, tipped,
                                  min((x.started for x in parts), default=None),
                                  max(x.finished for x in parts) if stored == kg else None,
                                  stored, moving, kg - stored - moving, tuple(dict.fromkeys(x.bin for x in parts)),
                                  on_route_kg=on_route)
        return out

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
        in_queue = {tid: 0 for tid in order}
        feasible = {tid: 0 for tid in order}
        for victim, by in self.dispatcher.overtake_log:
            v, b = owner(victim), owner(by)
            if v is None or b is None:
                continue
            in_queue[v] += 1
            if order[b] > order[v]:
                overtaken[v] += 1
                if victim.endswith("/tip"):
                    at_hopper[v] += 1
                if self._could_use(v, victim.split("/", 1)[1], b, by.split("/", 1)[1]):
                    feasible[v] += 1
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
            gate = (rec.admitted if rec.admitted is not None else stop) - rec.arrived
            metrics[tid] = TruckMetrics(
                truck_id=tid, activity=rec.activity, commodity=truck.commodity, grade=truck.grade,
                arrived=rec.arrived, gate_admitted=rec.admitted, queue_entered=entered,
                hopper_queue_entered=None if tip is None else tip.entered,
                hopper_admitted=None if tip is None else tip.started, departed=rec.departed,
                total_waiting_min=waiting, hopper_wait_min=hopper, overtaken_by_later=overtaken[tid],
                overtaken_at_hopper=at_hopper[tid], status=status, unfinished=status == "unfinished",
                turned_away=status == "turned_away", starved=starved,
                arrival_seq=order[tid], queue_seq=dict(self._queue_seq.get(tid, {})),
                overtaken_in_queue=in_queue[tid], overtaken_feasible=feasible[tid],
                overtaken_infeasible=overtaken[tid] - feasible[tid],
                pre_opening_wait_min=gate / MS_PER_MINUTE, operational_wait_min=waiting - gate / MS_PER_MINUTE,
                wait_censored=status == "unfinished")
        # Gate-arrival fairness at the hopper: later gate arrivals that started tipping before this truck did (or
        # before it left or the run ended, if it never tipped).
        tipped = sorted((x.hopper_admitted, order[t]) for t, x in metrics.items() if x.hopper_admitted is not None)
        for tid, x in metrics.items():
            if x.hopper_queue_entered is None and x.activity != "unload":
                continue
            rec = self.records[tid]
            until = x.hopper_admitted if x.hopper_admitted is not None else (
                rec.turned_away_at if rec.turned_away is not None else end)
            ahead = sum(1 for at, seq in tipped if at < until and seq > order[tid])
            metrics[tid] = dataclasses.replace(x, hopper_admitted_ahead_by_later_arrivals=ahead)
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
                    starved=sum(1 for x in group if x.starved), turned_away=sum(1 for x in group if x.turned_away),
                    **self._censoring_split(group, mean, rank))
            worst = max(ms, key=lambda x: (x.overtaken_by_later, -order[x.truck_id]))
            fairness[act] = ActivityFairness(by, worst.overtaken_by_later,
                                             worst.truck_id if worst.overtaken_by_later else None,
                                             sum(1 for x in ms if x.starved), limit_min, limit_overtakes)
        return {"truck_metrics": metrics, "fairness": fairness}

    @staticmethod
    def _censoring_split(group: list[TruckMetrics], mean, rank) -> dict:
        done = [x.total_waiting_min for x in group if x.status == "completed"]
        cens = [x.total_waiting_min for x in group if x.wait_censored]
        ahead = [x.hopper_admitted_ahead_by_later_arrivals for x in group]
        return dict(
            completed_mean_wait_min=mean(done), completed_median_wait_min=rank(done, 0.5),
            completed_p95_wait_min=rank(done, 0.95), completed_max_wait_min=max(done) if done else None,
            censored=len(cens), censored_mean_wait_min=mean(cens), censored_max_wait_min=max(cens) if cens else None,
            mean_pre_opening_wait_min=mean([x.pre_opening_wait_min for x in group]),
            mean_operational_wait_min=mean([x.operational_wait_min for x in group]),
            mean_admitted_ahead_by_later_arrivals=mean(ahead), max_admitted_ahead_by_later_arrivals=max(ahead),
            overtaken_feasible=sum(x.overtaken_feasible for x in group),
            overtaken_infeasible=sum(x.overtaken_infeasible for x in group))

    def _could_use(self, victim: str, victim_step: str, by: str, by_step: str) -> bool:
        """Static (configuration) test: is the equipment the overtaking truck obtained for `by_step` equipment the
        waiting truck could ever use for its own step? Not a test of whether it could have started at that moment."""
        unit = next((s.unit for s in self.records[by].steps if s.step == by_step and s.started is not None), None)
        truck = next(t for t in self.trucks if t.id == victim)
        if by_step == "tip" and unit in self.pits:
            return truck.commodity in self.pits[unit].accepts and self.planner.has_intake_route(unit, self._grain(truck))
        if by_step == "load" and unit is not None:
            return any(path[-1] == unit and any(g.commodity == truck.commodity for g in self.bins[b].accepts)
                       for b, paths in self.planner.routes.load.items() for path in paths)
        if by_step in STATION_TYPE and unit is not None:
            return any(u.resource == unit and u.serves(victim_step) for u in self.units)
        return True  # waiting areas and grading: any truck can use them

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
