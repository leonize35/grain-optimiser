"""Queue policies: the common interface through which a policy recommends which waiting request to admit next
(docs/QUEUE_POLICY_DESIGN.md).

A policy sees a read-only snapshot of one queue group's waiting requests and returns an order to try them in. It
never checks or reserves anything: physical eligibility, grain compatibility, route reservation, capacity and
changeovers stay in the engine (each request's ``attempt`` and the reservation ledger). The dispatcher attempts
requests in the recommended order and starts the first that the engine can start.

Built-in policies:

- ``strict_fifo`` (strict global FIFO): queue order, and once one request cannot start, no later request of the
  group may start in that pass. A blocked head holds back the whole group, even while a parallel unit (another
  hopper) that a later truck could use stands idle.
- ``feasible_first`` (work-conserving feasible-first FIFO): queue order; the first request that can start does.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .dispatcher import WaitReason


@dataclass(frozen=True)
class WaitingRequest:
    request_id: str
    group: str
    position: tuple[int, int]  # (order key, submission sequence): queue order at this stage
    queued_at: int  # entered this queue (ms)
    overtaken: int  # queue-order overtakes so far
    last_reasons: tuple[WaitReason, ...]  # why it could not start last time it was tried
    info: Mapping[str, object]  # read-only facts from the engine (truck id, gate arrival order, commodity, ...)


@dataclass(frozen=True)
class Recommendation:
    order: tuple[str, ...]  # request ids to try, in this order; ids left out are held back this pass
    stop_at_first_blocked: bool  # True: once a recommended request cannot start, no later one may start this pass


class QueuePolicy(Protocol):
    name: str

    def recommend(self, group: str, waiting: Sequence[WaitingRequest], now: int) -> Recommendation: ...


class StrictFifo:
    name = "strict_fifo"

    def recommend(self, group: str, waiting: Sequence[WaitingRequest], now: int) -> Recommendation:
        return Recommendation(tuple(w.request_id for w in sorted(waiting, key=lambda w: w.position)), True)


class FeasibleFirst:
    name = "feasible_first"

    def recommend(self, group: str, waiting: Sequence[WaitingRequest], now: int) -> Recommendation:
        return Recommendation(tuple(w.request_id for w in sorted(waiting, key=lambda w: w.position)), False)


BUILT_IN: dict[str, type] = {"strict_fifo": StrictFifo, "feasible_first": FeasibleFirst}
POLICY_NAMES = tuple(BUILT_IN)
DEFAULT_POLICY = "feasible_first"  # unchanged default when neither the run nor the site names a policy
