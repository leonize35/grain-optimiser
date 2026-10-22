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
    open: float
    close: float
    overtime: float = 0


class Sequences(_Model):
    unload: list[TruckStep] = []
    load: list[TruckStep] = []
    weigh: list[TruckStep] = []


class ActivityDemand(_Model):
    daily: float = 0
    profile: list[float] | None = None  # 24 hourly weights
    payload: list[float] | None = None  # triangular [min, mode, max] tonnes
    mix: dict[str, float] = {}


class Demand(_Model):
    unload: ActivityDemand | None = None
    load: ActivityDemand | None = None
    weigh: ActivityDemand | None = None


class Policies(_Model):
    tip: Literal["fifo", "feasible", "batch"] = "fifo"
    weigh: Literal["fifo", "load_first", "out_first"] = "fifo"
    transfer: Literal["fifo", "batch", "load_first"] = "fifo"


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
    canonical = json.dumps(cfg.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
