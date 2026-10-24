"""Queue-policy mappings used in the Paper 2 evidence, including adversarial test policies (EV-P1).

The adversarial policies are built on the engine's public policy interface (`sim.queue_policy`); the engine is not
changed. They exist only to show that physical invariants do not depend on the queue policy. They are not proposed
as operating practice.

Named mappings (every queue group gets an explicit policy; see `docs/QUEUE_POLICY_DESIGN.md`):
- M-FF  feasible_first in every queue group (the engine's unchanged default).
- M-PT  prototype-equivalent: strict FIFO at the hopper (tip), feasible_first elsewhere (prototype `tip: "fifo"`).
- M-SF  strict FIFO in every queue group, including grain transfers. A stress case, NOT claimed to represent silo
        practice (the prototype never applies strict FIFO to transfers).
- ADV-REV   latest request first, work-conserving.
- ADV-RAND  seeded random order on every pass, work-conserving.
- ADV-RHOL  seeded random order, and the first blocked request blocks the rest of its queue (random head-of-line).
            Can create legitimate operational stalls; these are reported, not counted as verification failures.
"""
import random

from silo_engine.sim.queue_policy import FeasibleFirst, Recommendation, StrictFifo, from_prototype
from silo_engine.sim.random_streams import derived_seed
from silo_engine.sim.truck_flow import QUEUE_GROUP

GROUPS = sorted(set(QUEUE_GROUP.values()))


class ReverseOrder:
    name = "adv_reverse"

    def recommend(self, group, waiting, now):
        return Recommendation(tuple(w.request_id for w in sorted(waiting, key=lambda w: w.position, reverse=True)), False)


class RandomOrder:
    """Deterministic for a given seed: the recommendation sequence depends only on the order of calls."""

    def __init__(self, seed: int, head_of_line: bool):
        self.rng = random.Random(seed)
        self.head_of_line = head_of_line
        self.name = "adv_random_head_of_line" if head_of_line else "adv_random"

    def recommend(self, group, waiting, now):
        ids = [w.request_id for w in sorted(waiting, key=lambda w: w.position)]
        self.rng.shuffle(ids)
        return Recommendation(tuple(ids), self.head_of_line)


MAPPINGS = {
    "M-FF": "feasible_first in every queue group (engine default)",
    "M-PT": "strict FIFO at the hopper, feasible_first elsewhere (prototype tip='fifo' equivalent)",
    "M-SF": "strict FIFO in every queue group incl. grain transfers (stress case; not representative practice)",
    "ADV-REV": "adversarial: latest request first (work-conserving)",
    "ADV-RAND": "adversarial: seeded random order (work-conserving)",
    "ADV-RHOL": "adversarial: seeded random order with head-of-line blocking",
}


def policy_for(name: str, seed: int):
    """A fresh policy mapping {queue group: policy} for one run (adversarial policies carry per-run state)."""
    if name == "M-FF":
        return {g: "feasible_first" for g in GROUPS}
    if name == "M-PT":
        return from_prototype({"tip": "fifo", "weigh": "fifo", "transfer": "fifo"})
    if name == "M-SF":
        return {g: "strict_fifo" for g in GROUPS}
    if name == "ADV-REV":
        return {g: ReverseOrder() for g in GROUPS}
    if name in ("ADV-RAND", "ADV-RHOL"):
        return {g: RandomOrder(derived_seed(seed, "policy", name, g), name == "ADV-RHOL") for g in GROUPS}
    raise KeyError(name)


def describe(mapping: dict) -> dict[str, str]:
    return {g: (p if isinstance(p, str) else p.name) for g, p in sorted(mapping.items())}


__all__ = ["MAPPINGS", "policy_for", "describe", "FeasibleFirst", "StrictFifo"]
