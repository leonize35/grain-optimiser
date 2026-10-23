"""Service durations for truck steps.

`FixedServiceTimes` gives deterministic durations for hand-checkable tests and scripted replays.
`StochasticServiceTimes` draws each duration from the item's triangular [min, most likely, max] minutes in the
configuration (`time` for samplers, graders and weighbridges; `tip` for hoppers), using a stream keyed by the
truck and step, so a truck's times do not change when the layout or the order of events changes.
"""
from decimal import Decimal
from typing import Protocol

from ..config.schema import SiteConfig
from .random_streams import Stream, triangular
from .time import MS_PER_MINUTE, m


class ServiceTimes(Protocol):
    def duration_ms(self, truck_id: str, step: str, equipment_id: str) -> int: ...


class FixedServiceTimes:
    def __init__(self, minutes_by_step: dict[str, int | float | str],
                 overrides: dict[tuple[str, str], int | float | str] | None = None):
        self._by_step = {k: m(Decimal(str(v))) for k, v in minutes_by_step.items()}
        self._overrides = {k: m(Decimal(str(v))) for k, v in (overrides or {}).items()}

    def duration_ms(self, truck_id: str, step: str, equipment_id: str) -> int:
        if (truck_id, step) in self._overrides:
            return self._overrides[(truck_id, step)]
        if step not in self._by_step:
            raise KeyError(f"No service time given for step '{step}'")
        return self._by_step[step]


class StochasticServiceTimes:
    """Triangular durations from the configuration, one independent draw per (truck, step)."""

    def __init__(self, site: SiteConfig, seed: int):
        self._equipment = {e.id: e for e in site.equipment}
        self.seed = seed

    def duration_ms(self, truck_id: str, step: str, equipment_id: str) -> int:
        e = self._equipment[equipment_id]
        params = e.tip if step == "tip" else e.time
        if not params or len(params) < 3:
            raise ValueError(f"{e.name or e.id} has no [min, most likely, max] time for '{step}'")
        u = Stream(self.seed, "service", truck_id, step).uniform()
        return round(triangular(u, params[0], params[1], params[2]) * MS_PER_MINUTE)
