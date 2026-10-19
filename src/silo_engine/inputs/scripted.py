"""Scripted truck arrivals: an explicit list of trucks with fixed times, commodities and tonnages.

Used for hand-checkable tests (e.g. "first truck blocked, second feasible", which random demand cannot force)
and later for replaying a historical day. Format (JSON/dict):

    {"trucks": [
        {"id": "U1", "activity": "unload", "arrive": "07:00", "commodity": "YM", "tonnes": "32.125"},
        {"id": "W1", "activity": "weigh",  "arrive": "07:00"},
        {"id": "U0", "activity": "unload", "arrive": "06:00", "commodity": "WM", "tonnes": 30.5, "backlog": true}
    ]}

- arrive: clock time "HH:MM[:SS]" or minutes from midnight.
- unload/load trucks need commodity and tonnes (decimal tonnes, at most 3 decimals); weigh-only trucks have neither.
- backlog: truck already waiting at that time (scheduled with CONTROL priority, i.e. before new arrivals at the
  same instant, as the prototype does for its opening queue).
- Trucks arriving at the same instant keep their order in the script.
"""
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from ..config.schema import SiteConfig
from ..domain.quantities import QuantityError, tonnes_to_kg
from ..sim.calendar import ARRIVAL, CONTROL, Calendar
from ..sim.time import TimeFormatError, format_clock, m, parse_time

Activity = Literal["unload", "load", "weigh"]


class ScriptError(ValueError):
    pass


class _TruckEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    activity: Activity
    arrive: str | int | float
    commodity: str | None = None
    tonnes: str | int | float | None = None
    backlog: bool = False


class _Script(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trucks: list[_TruckEntry]


@dataclass(frozen=True)
class ScriptedTruck:
    id: str
    activity: Activity
    arrive_ms: int
    commodity: str | None
    kg: int | None
    backlog: bool


def load_arrival_script(raw: dict[str, Any]) -> list[ScriptedTruck]:
    try:
        script = _Script.model_validate(raw)
    except ValidationError as e:
        problems = []
        for err in e.errors():
            loc = err["loc"]
            where = ".".join(str(p) for p in loc)
            if len(loc) >= 2 and loc[0] == "trucks" and isinstance(loc[1], int) and loc[1] < len(raw.get("trucks", [])):
                truck_id = raw["trucks"][loc[1]].get("id")
                if truck_id:
                    where = f"truck {truck_id} ({where})"
            problems.append(f"{where}: {err['msg']}")
        raise ScriptError("; ".join(problems)) from None

    trucks: list[ScriptedTruck] = []
    seen: set[str] = set()
    for t in script.trucks:
        if t.id in seen:
            raise ScriptError(f"Truck id {t.id} is used more than once.")
        seen.add(t.id)
        try:
            arrive = parse_time(t.arrive)
        except TimeFormatError as e:
            raise ScriptError(f"Truck {t.id}: {e}") from None
        if t.activity == "weigh":
            if t.commodity is not None or t.tonnes is not None:
                raise ScriptError(f"Truck {t.id} is weighbridge-only and cannot carry a commodity or tonnes.")
            kg = None
        else:
            if t.commodity is None or t.tonnes is None:
                raise ScriptError(f"Truck {t.id} ({t.activity}) needs both a commodity and tonnes.")
            try:
                kg = tonnes_to_kg(t.tonnes)
            except QuantityError as e:
                raise ScriptError(f"Truck {t.id}: {e}") from None
        trucks.append(ScriptedTruck(t.id, t.activity, arrive, t.commodity, kg, t.backlog))
    return trucks


def schedule_arrivals(cal: Calendar, trucks: list[ScriptedTruck],
                      on_arrival: Callable[[Calendar, ScriptedTruck], None]) -> None:
    """Put each truck's arrival on the calendar. Script order is scheduling order, so equal times keep it."""
    for truck in trucks:
        cal.schedule(truck.arrive_ms, CONTROL if truck.backlog else ARRIVAL,
                     lambda c, tr=truck: on_arrival(c, tr), f"{truck.id} arrives")


def _hours_ms(hours: float) -> int:
    return m(Decimal(str(hours)) * 60)


def check_script_against_site(trucks: list[ScriptedTruck], site: SiteConfig) -> list[str]:
    """Manager-language problems with a script for this site (empty list when it fits).

    Arrival exactly at closing time is accepted (assumption: the gate closes after it; the prototype generates
    random arrivals strictly before closing)."""
    problems: list[str] = []
    commodities = {c.id for c in site.commodities}
    opens, closes = _hours_ms(site.hours.open), _hours_ms(site.hours.close)
    for t in trucks:
        if t.commodity is not None and t.commodity not in commodities:
            problems.append(f"Truck {t.id} brings {t.commodity}, which is not a commodity at {site.name}.")
        if t.arrive_ms > closes:
            problems.append(f"Truck {t.id} arrives at {format_clock(t.arrive_ms)}, after the site closes at {format_clock(closes)}.")
        elif t.arrive_ms < opens:
            problems.append(f"Truck {t.id} arrives at {format_clock(t.arrive_ms)}, before the site opens at {format_clock(opens)}.")
    return problems
