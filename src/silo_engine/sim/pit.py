"""Hopper pit: grain inventory separate from the truck (R2).

- Tipped grain becomes a *lot* (truck id, commodity and grade, kilograms). Lots leave the pit in order.
- While a transfer drains the pit, the level falls **continuously** (assumption A3), so space for the next
  truck appears gradually. Committed quantities change only when the drain finishes; `level_at(t)` and
  `free_space_at(t)` give the continuous view used for admission.
- A pit holds one commodity and grade at a time (A4), unless the site's grade mixing rules (R4) let two grades
  of the same commodity share it.
- Admission rules (site input): ``full_load_space`` (free space ≥ load) or ``empty_pit`` (nothing in the pit).
- Space for a truck that is tipping is held by a *claim* until tipping ends, when the claim becomes a lot.
"""
import math
from collections import deque
from dataclasses import dataclass
from fractions import Fraction

from ..domain.storage import GradedCommodity, MixingRules
from .dispatcher import WaitReason

ADMISSION_RULES = ("full_load_space", "empty_pit")


@dataclass
class Lot:
    id: str
    truck_id: str | None  # None for opening stock
    grain: GradedCommodity
    kg: int  # still in the pit
    created: int


@dataclass
class Drain:
    """A discharge of `kg` from the head lot. The rate (kg per ms) may change while it runs (shared equipment);
    `drained_before` holds what left the pit before `since`, when the current rate took effect."""
    lot_id: str
    kg: int
    start: int  # flow starts (after any changeover)
    rate: Fraction  # kg per ms
    since: int
    drained_before: Fraction = Fraction(0)


class PitError(RuntimeError):
    pass


class Pit:
    def __init__(self, pit_id: str, capacity_kg: int, rate_tph: Fraction, admission: str, accepts: set[str],
                 lots: list[Lot] | None = None, mixing: MixingRules | None = None):
        if admission not in ADMISSION_RULES:
            raise PitError(f"{pit_id}: unknown tipping rule '{admission}'")
        self.id = pit_id
        self.capacity_kg = capacity_kg
        self.rate_tph = rate_tph
        self.admission = admission
        self.accepts = accepts
        self.mixing = mixing or MixingRules([])
        self.lots: deque[Lot] = deque(lots or [])
        self.claims: dict[str, tuple[GradedCommodity, int]] = {}
        self.draining: Drain | None = None
        self._version = 0  # bumped on every change; keys the free-space cache
        self._free_cache: tuple[int, int, Fraction] | None = None

    def _changed(self) -> None:
        self._version += 1
        self._free_cache = None

    # ---- level ----
    @property
    def committed_kg(self) -> int:
        return sum(lot.kg for lot in self.lots)

    def drained_at(self, now: int) -> Fraction:
        d = self.draining
        if d is None:
            return Fraction(0)
        elapsed = max(now - max(d.since, d.start), 0)
        return min(Fraction(d.kg), d.drained_before + d.rate * elapsed)

    def level_at(self, now: int) -> Fraction:
        return self.committed_kg - self.drained_at(now)

    def free_space_at(self, now: int) -> Fraction:
        cached = self._free_cache
        if cached is not None and cached[0] == now and cached[1] == self._version:
            return cached[2]
        free = self.capacity_kg - self.level_at(now) - sum(kg for _, kg in self.claims.values())
        self._free_cache = (now, self._version, free)
        return free

    def _combined(self, extra: list[GradedCommodity]) -> tuple[bool, GradedCommodity | None]:
        identity = None
        for grain in [lot.grain for lot in self.lots] + [g for g, _ in self.claims.values()] + extra:
            if identity is None:
                identity = grain
            else:
                combined = self.mixing.combine(identity, grain)
                if combined is None:
                    return False, identity
                identity = combined
        return True, identity

    def identity(self) -> GradedCommodity | None:
        return self._combined([])[1]

    # ---- admission ----
    def check_claim(self, now: int, grain: GradedCommodity, kg: int) -> list[WaitReason]:
        reasons: list[WaitReason] = []
        current = self.identity()
        if current is not None and not self._combined([grain])[0]:
            reasons.append(WaitReason("PIT_INCOMPATIBLE", self.id,
                                      f"{self.id} holds {current.commodity}; {grain.commodity} must wait until it is empty"))
        if self.admission == "empty_pit":
            if self.lots or self.claims:
                reasons.append(WaitReason("PIT_SPACE", self.id, f"{self.id} must be empty before the next truck tips"))
        elif self.free_space_at(now) < kg:
            reasons.append(WaitReason("PIT_SPACE", self.id,
                                      f"{self.id} has {math.floor(self.free_space_at(now))} kg free, {kg} kg needed"))
        return reasons

    def time_space_available(self, now: int, kg: int) -> int | None:
        """Earliest time ≥ now at which `kg` will fit under the current drain, or None if not before it ends."""
        if self.admission != "full_load_space":
            return None
        shortfall = kg - self.free_space_at(now)
        if shortfall <= 0:
            return now
        d = self.draining
        if d is None or d.rate == 0:
            return None
        drained_needed = self.drained_at(now) + shortfall
        if drained_needed > d.kg:
            return None
        base = max(now, d.start, d.since)  # predicted at the current rate; a rate change triggers a new prediction
        return base + math.ceil((drained_needed - self.drained_at(base)) / d.rate)

    def claim(self, reservation_id: str, grain: GradedCommodity, kg: int) -> None:
        if reservation_id in self.claims:
            raise PitError(f"{self.id}: claim {reservation_id} already exists")
        self.claims[reservation_id] = (grain, kg)
        self._changed()

    def release_claim(self, reservation_id: str) -> None:
        self.claims.pop(reservation_id, None)
        self._changed()

    def claim_to_lot(self, reservation_id: str, lot: Lot) -> None:
        grain, kg = self.claims.pop(reservation_id)
        if (grain, kg) != (lot.grain, lot.kg):
            raise PitError(f"{self.id}: lot {lot.id} does not match claim {reservation_id}")
        self.lots.append(lot)
        self._changed()

    # ---- draining ----
    def start_drain(self, kg: int, start: int, duration: int | None = None) -> None:
        """Reserve the outlet for `kg` from the head lot, flowing from `start`. With `duration` the rate is fixed
        (kg / duration); without it the rate is 0 until `set_rate` is called when the flow begins."""
        if self.draining is not None:
            raise PitError(f"{self.id} is already discharging")
        if not self.lots or kg > self.lots[0].kg or kg <= 0:
            raise PitError(f"{self.id}: cannot drain {kg} kg from the head lot")
        rate = Fraction(kg, duration) if duration else Fraction(0)
        self.draining = Drain(self.lots[0].id, kg, start, rate, start)
        self._changed()

    def set_rate(self, now: int, rate: Fraction) -> None:
        d = self.draining
        if d is None:
            raise PitError(f"{self.id} is not discharging")
        d.drained_before = self.drained_at(now)
        d.since = max(now, d.start)
        d.rate = rate
        self._changed()

    def remaining_drain_kg(self, now: int) -> Fraction:
        d = self.draining
        return Fraction(0) if d is None else d.kg - self.drained_at(now)

    def finish_drain(self, now: int) -> Lot:
        d = self.draining
        if d is None or self.drained_at(now) < d.kg:
            raise PitError(f"{self.id}: drain finished before all grain had left")
        head = self.lots[0]
        head.kg -= d.kg
        self.draining = None
        if head.kg == 0:
            self.lots.popleft()
        self._changed()
        return head

    def check_invariants(self, now: int) -> list[str]:
        problems = []
        if self.level_at(now) < 0:
            problems.append(f"{self.id}: negative level")
        if self.level_at(now) + sum(kg for _, kg in self.claims.values()) > self.capacity_kg:
            problems.append(f"{self.id}: grain plus claimed space exceeds pit capacity")
        if not self._combined([])[0]:
            problems.append(f"{self.id}: grain in the pit that may not be mixed")
        return problems
