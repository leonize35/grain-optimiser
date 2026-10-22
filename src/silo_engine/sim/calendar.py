"""Discrete-event calendar with deterministic ordering (port of the prototype `Calendar`).

Events are executed in order of (time, priority, sequence):
- time: integer milliseconds (see sim/time.py);
- priority, for events at the same instant, same classes as the prototype:
    RELEASE (0) completions and releases first, so capacity freed at t is visible to everything else at t;
    CONTROL (1) control events (opening backlog, end of day);
    ARRIVAL (2) new trucks last;
- sequence: the order in which events were scheduled (first scheduled, first executed).

Differences from the prototype: scheduling in the past raises instead of recording a violation (it can only be
an engine bug); non-integer times are refused; events can be cancelled (needed later for interruptions).
"""
import heapq
from collections.abc import Callable
from dataclasses import dataclass, field

RELEASE = 0
CONTROL = 1
ARRIVAL = 2
PRIORITIES = (RELEASE, CONTROL, ARRIVAL)

Action = Callable[["Calendar"], None]


class SchedulingError(RuntimeError):
    pass


@dataclass(eq=False)
class Event:
    time: int
    priority: int
    seq: int
    action: Action | None = field(repr=False)
    label: str
    cancelled: bool = False
    done: bool = False


class Calendar:
    def __init__(self, start: int = 0) -> None:
        self.now = start
        self._heap: list[tuple[int, int, int, Event]] = []
        self._seq = 0
        self.log: list[Event] = []  # executed events, in execution order

    def schedule(self, time: int, priority: int, action: Action | None, label: str) -> Event:
        if type(time) is not int:
            raise SchedulingError(f"'{label}': time must be whole milliseconds, got {time!r}")
        if priority not in PRIORITIES:
            raise SchedulingError(f"'{label}': unknown priority {priority!r}")
        if time < self.now:
            raise SchedulingError(f"'{label}' scheduled at {time} ms, before the current time {self.now} ms")
        event = Event(time, priority, self._seq, action, label)
        self._seq += 1
        heapq.heappush(self._heap, (time, priority, event.seq, event))
        return event

    def cancel(self, event: Event) -> None:
        if event.done:
            raise SchedulingError(f"'{event.label}' has already happened and cannot be cancelled")
        event.cancelled = True

    def _drop_cancelled(self) -> None:
        while self._heap and self._heap[0][3].cancelled:
            heapq.heappop(self._heap)

    def peek_time(self) -> int | None:
        self._drop_cancelled()
        return self._heap[0][0] if self._heap else None

    @property
    def pending(self) -> int:
        return sum(1 for *_, e in self._heap if not e.cancelled)

    def pending_events(self) -> list[Event]:
        """Events still to happen (not cancelled), in no particular order."""
        return [e for *_, e in self._heap if not e.cancelled]

    def cancel_all(self) -> None:
        for e in self.pending_events():
            e.cancelled = True

    def step(self) -> Event | None:
        """Execute the next event; returns it, or None when nothing is left."""
        self._drop_cancelled()
        if not self._heap:
            return None
        time, _, _, event = heapq.heappop(self._heap)
        self.now = time
        if event.action is not None:
            event.action(self)
        event.done = True
        self.log.append(event)
        return event

    def run(self, until: int | None = None) -> None:
        """Execute events in order. With `until`, events at exactly `until` run, later ones stay queued,
        and the clock ends at `until`."""
        while True:
            t = self.peek_time()
            if t is None or (until is not None and t > until):
                break
            self.step()
        if until is not None and self.now < until:
            self.now = until
