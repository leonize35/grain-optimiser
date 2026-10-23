"""Central dispatcher: one place that decides which waiting request starts next.

Requests belong to a *queue group* (e.g. "sample", "grade", "weigh", "tip", "intake", "load", "move").
Each group has a queue policy (``queue_policy.QueuePolicy``): on every pass the policy sees a read-only snapshot of
the group's waiting requests and recommends an order; the dispatcher attempts them in that order (docs/
QUEUE_POLICY_DESIGN.md). The built-in policies:

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
import heapq
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .queue_policy import BUILT_IN, POLICY_NAMES, QueuePolicy, WaitingRequest

POLICIES = POLICY_NAMES
_NO_INFO: Mapping[str, object] = MappingProxyType({})


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
    info: Mapping[str, object] = field(default=_NO_INFO, repr=False)

    def position(self) -> tuple[int, int]:
        return (self.order() if self.order else self.created, self.seq)


class DispatcherError(RuntimeError):
    pass


class Dispatcher:
    def __init__(self, policies: Mapping[str, "str | QueuePolicy"]):
        self._policies: dict[str, QueuePolicy] = {}
        for group, policy in policies.items():
            if isinstance(policy, str):
                if policy not in BUILT_IN:
                    raise DispatcherError(f"Unknown dispatch policy '{policy}' for {group}; use one of {POLICIES}")
                policy = BUILT_IN[policy]()
            self._policies[group] = policy
        self._pending: list[_Pending] = []
        self._seq = 0
        self._overtaken: dict[str, int] = {}
        self.overtake_log: list[tuple[str, str]] = []  # (overtaken request, request that started ahead of it)

    def submit(self, request_id: str, group: str, now: int, attempt: Attempt,
               order: Callable[[], int] | None = None, info: Mapping[str, object] | None = None) -> int:
        """Queue a request and return its submission sequence number (queue-entry order). Requests are positioned
        by (order key, submission sequence); the order key defaults to the submission time, so by default this is
        plain submission order. Grain transfers pass the age of their grain instead, giving "oldest grain first"
        across pits (the prototype's transfer rule). `info` is shown read-only to the group's policy."""
        if group not in self._policies:
            raise DispatcherError(f"No dispatch policy configured for queue group '{group}'")
        if any(p.id == request_id for p in self._pending):
            raise DispatcherError(f"Request {request_id} is already waiting")
        seq = self._seq
        self._pending.append(_Pending(request_id, group, now, seq, attempt, order,
                                      info=MappingProxyType(dict(info)) if info else _NO_INFO))
        self._seq += 1
        return seq

    def reconsider(self, now: int) -> None:
        """Start every request that can start now, respecting each group's policy."""
        while self._one_pass(now):
            pass

    def _attempt_sequence(self, now: int) -> tuple[list[_Pending], set[str]]:
        """Ask each group's policy for its order, then merge the groups' orders into one attempt sequence by the
        queue position of each order's next request. With position-ordered recommendations (both built-in
        policies) this is exactly the global sort by position. Returns the sequence and the groups whose policy
        stops at the first blocked request."""
        positions = {p.id: p.position() for p in self._pending}
        groups: dict[str, list[_Pending]] = {}
        for p in self._pending:
            groups.setdefault(p.group, []).append(p)
        orders: list[list[_Pending]] = []
        stopping: set[str] = set()
        for group, members in groups.items():
            views = [WaitingRequest(p.id, group, positions[p.id], p.created, self._overtaken.get(p.id, 0),
                                    tuple(p.reasons), p.info) for p in members]
            rec = self._policies[group].recommend(group, views, now)
            by_id = {p.id: p for p in members}
            if len(set(rec.order)) != len(rec.order) or any(i not in by_id for i in rec.order):
                raise DispatcherError(f"Queue policy for '{group}' recommended unknown or repeated requests: {rec.order}")
            chosen = set(rec.order)
            for p in members:
                if p.id not in chosen:
                    p.reasons = [WaitReason("POLICY_HOLD", None, "held back by the queue policy")]
            orders.append([by_id[i] for i in rec.order])
            if rec.stop_at_first_blocked:
                stopping.add(group)
        return list(heapq.merge(*orders, key=lambda p: positions[p.id])), stopping

    def _one_pass(self, now: int) -> bool:
        blocked_groups: set[str] = set()
        sequence, stopping = self._attempt_sequence(now)
        for req in sequence:
            if req.group in stopping and req.group in blocked_groups:
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
