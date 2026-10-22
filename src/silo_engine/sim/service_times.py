"""Service durations for truck steps.

`FixedServiceTimes` gives deterministic durations for hand-checkable tests and scripted replays.
Stochastic durations (triangular per station, drawn from a per-truck random stream as in the prototype) come
in a later step behind the same `duration_ms` interface.
"""
from decimal import Decimal
from typing import Protocol

from .time import m


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
