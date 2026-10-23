"""Central dispatcher: one place that decides which waiting request starts next.

Requests belong to a *queue group* (e.g. "sample", "grade", "weigh"; later "tip", "intake", "load").
Each group has an overtaking policy:

- ``strict_fifo``: a request may start only if no earlier request of the same group is still waiting.
  An earlier blocked request therefore holds up every later one in its group (head-of-line blocking).
- ``feasible_first``: requests are considered in submission order; a later request may start when an earlier
  one is blocked. Each time this happens the earlier request's *overtaken* count goes up, so fairness can be
  measured (no starvation limit yet; see GAP_MATRIX row 6).

Note: the prototype's weighbridge rule called ``fifo`` behaves like ``feasible_first`` here (it scans the whole
queue for any truck that fits a free weighbridge). This module keeps the two meanings apart.

The dispatcher owns ordering only. Whether a request can start, and claiming what it needs, is the request's
``attempt`` callable: it either starts the work and returns no reasons, or changes nothing and returns the
reasons it cannot start. After every start the scan restarts from the earliest request, because a start can
change what is possible for requests that were blocked a moment ago.
"""
from collections.abc import Callable
from dataclasses import dataclass, field

POLICIES = ("strict_fifo", "feasible_first")


@dataclass(frozen=True)
class WaitReason:
    code: str  # EQUIPMENT_BUSY, QUEUE_ORDER, GRADE_PENDING, ... (docs/ENGINE_INTERFACES.md §3)
    resource: str | None
    detail: str


Attempt = Callable[[int], list[WaitReason]]


@dataclass
class _Pending:
    id: str
    group: str
    created: int
    seq: int
    attempt: Attempt = field(repr=False)
    order: Callable[[], int] | None = field(default=None, repr=False)  # queue position key; default: `created`
    reasons: list[WaitReason] = field(default_factory=list)

    def position(self) -> tuple[int, int]:
        return (self.order() if self.order else self.created, self.seq)


class DispatcherError(RuntimeError):
    pass


class Dispatcher:
    def __init__(self, policies: dict[str, str]):
        for group, policy in policies.items():
            if policy not in POLICIES:
                raise DispatcherError(f"Unknown dispatch policy '{policy}' for {group}; use one of {POLICIES}")
        self._policies = dict(policies)
        self._pending: list[_Pending] = []
        self._seq = 0
        self._overtaken: dict[str, int] = {}
        self.overtake_log: list[tuple[str, str]] = []  # (overtaken request, request that started ahead of it)

    def submit(self, request_id: str, group: str, now: int, attempt: Attempt,
               order: Callable[[], int] | None = None) -> None:
        """Queue a request. Requests are considered by (order key, submission sequence); the order key defaults to
        the submission time, so by default this is plain submission order. Grain transfers pass the age of their
        grain instead, giving "oldest grain first" across pits (the prototype's transfer rule)."""
        if group not in self._policies:
            raise DispatcherError(f"No dispatch policy configured for queue group '{group}'")
        if any(p.id == request_id for p in self._pending):
            raise DispatcherError(f"Request {request_id} is already waiting")
        self._pending.append(_Pending(request_id, group, now, self._seq, attempt, order))
        self._seq += 1

    def reconsider(self, now: int) -> None:
        """Start every request that can start now, respecting each group's policy."""
        while self._one_pass(now):
            pass

    def _one_pass(self, now: int) -> bool:
        blocked_groups: set[str] = set()
        for req in sorted(self._pending, key=_Pending.position):
            if self._policies[req.group] == "strict_fifo" and req.group in blocked_groups:
                req.reasons = [WaitReason("QUEUE_ORDER", None, "waiting behind an earlier truck in the same queue")]
                continue
            position = req.position()
            reasons = req.attempt(now)
            if not reasons:
                self._pending.remove(req)
                for earlier in self._pending:
                    if earlier.position() < position and earlier.group == req.group:
                        self._overtaken[earlier.id] = self._overtaken.get(earlier.id, 0) + 1
                        self.overtake_log.append((earlier.id, req.id))
                return True
            req.reasons = reasons
            blocked_groups.add(req.group)
        return False

    def withdraw(self, request_id: str) -> bool:
        """Remove a waiting request (e.g. a truck sent away). Returns whether it was waiting."""
        for p in self._pending:
            if p.id == request_id:
                self._pending.remove(p)
                return True
        return False

    def pending_ids(self) -> list[str]:
        return [p.id for p in self._pending]

    def waiting_reasons(self) -> dict[str, list[WaitReason]]:
        return {p.id: list(p.reasons) for p in self._pending}

    def overtaken(self) -> dict[str, int]:
        return dict(self._overtaken)
