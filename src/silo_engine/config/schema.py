"""Typed site configuration schema.

Field names match the prototype's JSON so existing configurations load unchanged. The schema checks *shape*
(types, known fields, known rules and steps). Whether the silo makes physical and operational sense is checked
by `validate()`, which reports problems in manager language. For that reason numeric capacities are optional
here: a missing capacity is a validation error with a plain explanation, not a schema error.

Intentional differences from the prototype (which accepts anything):
- unknown fields are rejected (catches misspellings such as `capacity` for `capT`);
- operating rules and truck steps must come from the supported lists;
- weighbridge direction must be `in`, `out` or `both`.
"""
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Activity = Literal["unload", "load", "weigh"]
TruckStep = Literal["sample", "grade", "weigh_in", "tip", "load", "weigh_out"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Commodity(_Model):
    id: str
    name: str
    color: str | None = None
    grades: list[str] | None = None  # R4; None = ungraded commodity


class BinAccept(_Model):
    """R4: grades of one of the bin's commodities that the bin may hold."""
    commodity: str
    grades: list[str]


class GradeMixingRule(_Model):
    """R4: these grades of `commodity` may share a bin or pit; the mixture is classified as `result`."""
    commodity: str
    grades: list[str]
    result: str


class Equipment(_Model):
    id: str
    type: str  # checked by validate() so an unsupported type gets a manager-language message
    name: str | None = None
    cap: float | None = None  # trucks served at once (sampler, grader, weighbridge)
    time: list[float] | None = None  # triangular [min, mode, max] minutes
    moves: Literal["in", "out", "both"] | None = None  # weighbridge direction; None means both
    reject: float | None = None  # grader rejection probability
    cap_t: float | None = Field(default=None, alias="capT")  # tonnes (hopper pit, bin)
    rate: float | None = None  # tonnes per hour
    tip: list[float] | None = None  # hopper tipping time [min, mode, max] minutes
    changeover: float | None = None  # minutes
    setup: list[float] | None = None  # load point setup [min, mode, max] minutes
    commodities: list[str] | None = None
    accepts: list[BinAccept] | None = None  # R4 (bins): grades accepted per graded commodity
    inv: float | None = None  # opening bin stock, tonnes
    inv_commodity: str | None = Field(default=None, alias="invCommodity")
    inv_grade: str | None = Field(default=None, alias="invGrade")
    level0: float | None = None  # opening hopper level, tonnes
    level_commodity: str | None = Field(default=None, alias="levelCommodity")
    level_grade: str | None = Field(default=None, alias="levelGrade")
    # R2: when a truck may start tipping (site input). 'partial' is specified but not built until confirmed.
    tip_admission: Literal["full_load_space", "empty_pit"] = "full_load_space"
    # R1: streams that may feed this conveyor/elevator at once; 1 = exclusive (default, as in the prototype).
    max_concurrent_feeds: int = Field(default=1, ge=1)
    # R1: minutes the route stays reserved after the last grain is fed (equipment emptying). Site input.
    clear_minutes: float = Field(default=0, ge=0)


class Hours(_Model):
    """Clock hours (7.5 = 07:30). R6: the gate admits trucks from `open` until `admission_cutoff` (default:
    `close`); services may start until `close` + `overtime` hours (the hard stop)."""
    open: float
    close: float
    overtime: float = Field(default=0, ge=0)
    admission_cutoff: float | None = None


class EndOfDay(_Model):
    """R6 end-of-day policies (site input)."""
    unfinished_trucks: Literal["carry_over", "turned_away"] = "carry_over"
    late_arrivals: Literal["queue_for_next_day", "turned_away"] = "queue_for_next_day"
    transfers_after_close: bool = True


class Sequences(_Model):
    unload: list[TruckStep] = []
    load: list[TruckStep] = []
    weigh: list[TruckStep] = []


class ActivityDemand(_Model):
    daily: float = 0
    profile: list[float] | None = None  # 24 hourly weights
    payload: list[float] | None = None  # triangular [min, mode, max] tonnes
    mix: dict[str, float] = {}
    grade_mix: dict[str, dict[str, float]] = {}  # R4: per graded commodity, share of each grade


class Demand(_Model):
    unload: ActivityDemand | None = None
    load: ActivityDemand | None = None
    weigh: ActivityDemand | None = None


class Policies(_Model):
    """Prototype-format policies (kept for configuration parity with the prototype). NOT applied by this engine: the
    authoritative setting is `queue_policies`. `sim.queue_policy.from_prototype` is the one translation; a run notes
    in its assumptions when these differ from what it used (docs/QUEUE_POLICY_DESIGN.md §9)."""
    tip: Literal["fifo", "feasible", "batch"] = "fifo"
    weigh: Literal["fifo", "load_first", "out_first"] = "fifo"
    transfer: Literal["fifo", "batch", "load_first"] = "fifo"


QueueGroupName = Literal["sample", "grade", "weigh", "tip", "intake", "move", "load"]
QueuePolicyName = Literal["strict_fifo", "feasible_first"]


class QueuePolicies(_Model):
    """Queue policy per queue group (docs/QUEUE_POLICY_DESIGN.md), Python names. `strict_fifo` = strict global
    FIFO; `feasible_first` = work-conserving feasible-first FIFO. A run or experiment argument overrides this.
    (The prototype-format `policies` field is validated but not used by the Python engine.)"""
    default: QueuePolicyName = "feasible_first"
    groups: dict[QueueGroupName, QueuePolicyName] = {}


class ChangeoverRule(_Model):
    """R3: minutes needed on equipment before `to` grain may follow `from` grain.

    `from`/`to`: a commodity id, 'commodity:grade', or '*' (any). `equipment`: '*', or a list of equipment ids
    and/or types (conveyor, elevator). The most specific rule wins: id > type > '*', then grade > commodity > '*'.
    """
    from_: str = Field(alias="from")
    to: str
    minutes: float = Field(ge=0)
    equipment: Literal["*"] | list[str] = "*"


class Changeovers(_Model):
    # None: no default; a commodity pair that can meet on shared equipment without a rule is a configuration error.
    default_minutes: float | None = Field(default=None, ge=0)
    rules: list[ChangeoverRule] = []


class OpeningQueue(_Model):
    unload: int = 0
    load: int = 0
    weigh: int = 0


class Initial(_Model):
    queue: OpeningQueue = OpeningQueue()


class FairnessReporting(_Model):
    """Q1: starvation is reported, not prevented. A truck counts as starved when its total waiting reaches
    `starvation_wait_minutes`, or (if set) when later arrivals have overtaken it `starvation_overtakes` times."""
    starvation_wait_minutes: float = Field(default=120, ge=0)
    starvation_overtakes: int | None = Field(default=None, ge=1)


class Outage(_Model):
    """A scheduled period during which one piece of route equipment is unavailable (docs/INTERRUPTED_TRANSFERS.md).
    `end` None: not available again before the end of the run."""
    equipment: str
    day: int = Field(default=1, ge=1)
    start: str  # "HH:MM"
    end: str | None = None


class StockEvent(_Model):
    """Step 18 (docs/STOCK_ADJUSTMENTS.md): a scheduled process loss, stock measurement or book correction."""
    kind: Literal["process_loss", "stock_measurement", "book_correction"]
    day: int = Field(default=1, ge=1)
    time: str  # "HH:MM"
    bin: str
    id: str | None = None  # required for stock_measurement (referenced by measurement-based corrections)
    tonnes: float | None = None  # process_loss (positive) or administrative book_correction (signed)
    cause: Literal["moisture", "cleaning", "handling", "other"] | None = None  # process_loss
    posted: bool = True  # process_loss: also recorded in the book
    commodity: str | None = None  # process_loss: optional check of the bin's contents
    observed_tonnes: float | None = None  # stock_measurement
    basis: Literal["administrative", "measurement"] | None = None  # book_correction
    observation: str | None = None  # book_correction with basis "measurement"
    reason: str | None = None  # book_correction (required)
    authority: str | None = None  # book_correction (required)


class OpeningBook(_Model):
    bin: str
    tonnes: float = Field(ge=0)


class ReconciliationSettings(_Model):
    """Reporting tolerance for survey-versus-book variances; none by default (no universal percentage). When both
    are given, the larger allowance applies."""
    tolerance_t: float | None = Field(default=None, ge=0)
    tolerance_fraction: float | None = Field(default=None, ge=0)  # of the book quantity


class TruckArea(_Model):
    """R5: a physical waiting area for trucks. capacity None = unlimited (reported as a simplification)."""
    id: str
    name: str
    capacity: int | None = Field(default=None, ge=1)


class TruckPaths(_Model):
    """R5: per activity, the truck's physical path: waiting-area ids and truck steps in order. Its steps must equal
    the activity's sequence. Without a path, trucks have unlimited waiting space between steps."""
    unload: list[str] | None = None
    load: list[str] | None = None
    weigh: list[str] | None = None


class SiteConfig(_Model):
    id: str
    name: str
    version: int
    customer: str | None = None
    region: str | None = None
    hours: Hours
    commodities: list[Commodity]
    equipment: list[Equipment]
    edges: list[tuple[str, str]]
    sequences: Sequences
    demand: Demand
    policies: Policies = Policies()
    initial: Initial = Initial()
    # R3. None = prototype format: each conveyor/elevator's single `changeover` value applies to any commodity change.
    changeovers: Changeovers | None = None
    # R4. For graded commodities: 'none' records grades without restricting bins or pits; otherwise (default) every
    # bin holding a graded commodity must list the grades it accepts.
    grade_segregation: Literal["by_grade", "none"] | None = None
    grade_mixing: list[GradeMixingRule] = []
    # R5. Default reserve_next_space: a truck starts a service only with a place reserved in the next finite area.
    truck_areas: list[TruckArea] = []
    truck_paths: TruckPaths = TruckPaths()
    deadlock_prevention: Literal["reserve_next_space", "detect_only"] = "reserve_next_space"
    end_of_day: EndOfDay = EndOfDay()
    fairness: FairnessReporting = FairnessReporting()
    queue_policies: QueuePolicies | None = None  # None: the run's argument, else feasible_first
    outages: list[Outage] = []  # scheduled equipment unavailability (step 17)
    # Step 18: stock events, opening book inventory (default: equal to physical), reporting tolerance, authorities.
    stock_events: list[StockEvent] = []
    opening_book: list[OpeningBook] = []
    reconciliation: ReconciliationSettings = ReconciliationSettings()
    authorised_by: list[str] | None = None  # when set, a book correction's authority must be one of these


class ConfigSchemaError(ValueError):
    """The configuration does not have the expected shape. `problems` lists 'location: message' strings."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("The configuration could not be read:\n" + "\n".join("- " + p for p in problems))


def load_site_config(raw: dict[str, Any]) -> SiteConfig:
    try:
        return SiteConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigSchemaError(
            [".".join(str(p) for p in err["loc"]) + ": " + err["msg"] for err in e.errors()]
        ) from None


def config_hash(cfg: SiteConfig) -> str:
    """SHA-256 of the canonical JSON form; identifies the exact configuration a run used."""
    data = cfg.model_dump(mode="json", by_alias=True)
    for added, unset in (("queue_policies", None), ("outages", []), ("stock_events", []), ("opening_book", []),
                         ("reconciliation", {"tolerance_t": None, "tolerance_fraction": None}),
                         ("authorised_by", None)):  # not set: hash as before the setting existed
        if data.get(added) == unset:
            data.pop(added, None)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
