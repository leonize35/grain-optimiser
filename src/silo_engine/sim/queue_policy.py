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


# ---- the prototype's policy names (configuration field `policies`) ----
# The single translation from the prototype's `policies` to these queue policies. The prototype's own code is a frozen
# reference, not a second implementation: tests/test_policy_equivalence.py checks this table against its decisions.
PROTOTYPE_DEFAULTS = {"tip": "fifo", "weigh": "fifo", "transfer": "fifo"}  # the prototype's Object.assign defaults
PROTOTYPE_EQUIVALENTS: dict[tuple[str, str], dict[str, str]] = {
    ("tip", "fifo"): {"tip": "strict_fifo"},  # dispatchTip tries only the queue head
    ("tip", "feasible"): {"tip": "feasible_first"},  # dispatchTip scans the whole queue
    ("weigh", "fifo"): {"weigh": "feasible_first"},  # dispatchPool scans the whole queue for a fitting weighbridge
    ("transfer", "fifo"): {"intake": "feasible_first", "load": "feasible_first"},  # oldest first, whole list scanned
}
# Queues the prototype always scans in full (no setting), and the Python-only waiting-area queue.
PROTOTYPE_FIXED = {"sample": "feasible_first", "grade": "feasible_first", "move": "feasible_first"}
PROTOTYPE_UNSUPPORTED = {
    ("tip", "batch"): "hopper-led commodity batching (each free hopper takes the earliest truck of its commodity)",
    ("weigh", "load_first"): "loading trucks weighed first",
    ("weigh", "out_first"): "outbound weighings first",
    ("transfer", "batch"): "a route-choice rule (prefer routes without changeover), not a queue order",
    ("transfer", "load_first"): "loading transfers before intake transfers",
}


class UnsupportedPrototypePolicy(ValueError):
    """A prototype policy with no equivalent here. Not approximated: the run must name a supported policy."""


def from_prototype(policies: Mapping[str, str] | None) -> dict[str, str]:
    """Queue policy per queue group equivalent to the prototype's `policies` (missing keys take the prototype's
    defaults). Raises UnsupportedPrototypePolicy for rules not ported (BATCH, load_first, out_first)."""
    chosen = {**PROTOTYPE_DEFAULTS, **dict(policies or {})}
    out = dict(PROTOTYPE_FIXED)
    for key, value in chosen.items():
        if (key, value) in PROTOTYPE_UNSUPPORTED:
            raise UnsupportedPrototypePolicy(
                f"Prototype policy {key}='{value}' ({PROTOTYPE_UNSUPPORTED[key, value]}) has no equivalent in this "
                "engine yet; choose strict_fifo or feasible_first in queue_policies.")
        if (key, value) not in PROTOTYPE_EQUIVALENTS:
            raise UnsupportedPrototypePolicy(f"Unknown prototype policy {key}='{value}'.")
        out.update(PROTOTYPE_EQUIVALENTS[key, value])
    return out
