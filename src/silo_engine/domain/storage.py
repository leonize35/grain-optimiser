"""Storage bins: inventory, identity (commodity and grade), reservations and assignment (R7, R4).

Rules are specified in docs/DOMAIN_DECISIONS.md (R7). Quantities are whole kilograms.

Two kinds of failure are kept apart:
- `Refused`: the request is legitimate but not possible right now (bin full, wrong grade, out of service).
  `check_*` methods return it with reason codes; `reserve_*` / `reassign` raise it. Either way nothing changes.
- `BinError`: the engine used the bin incorrectly (unknown reservation, over-delivery, reused id). That is a bug.
"""
from dataclasses import dataclass
from fractions import Fraction
from typing import NamedTuple


class GradedCommodity(NamedTuple):
    commodity: str
    grade: str


@dataclass(frozen=True)
class Reason:
    code: str  # BIN_NOT_ALLOWED, BIN_INCOMPATIBLE, BIN_FULL, STOCK_SHORT, OUT_OF_SERVICE
    detail: str


class Refused(Exception):
    def __init__(self, reasons: list[Reason]):
        self.reasons = reasons
        super().__init__("; ".join(r.detail for r in reasons))


class BinError(RuntimeError):
    pass


class MixingRules:
    """Grades of one commodity that may share a bin or pit, and the grade the mixture is classified as.

    Each rule: (commodity, grades that may share, resulting grade). With no matching rule, only identical
    commodity and grade combine.
    """

    def __init__(self, rules: list[tuple[str, set[str], str]]):
        self._rules = [(c, frozenset(g), r) for c, g, r in rules]

    def combine(self, a: GradedCommodity, b: GradedCommodity) -> GradedCommodity | None:
        if a == b:
            return a
        if a.commodity != b.commodity:
            return None
        for commodity, grades, result in self._rules:
            if commodity == a.commodity and {a.grade, b.grade} <= grades:
                return GradedCommodity(commodity, result)
        return None


class StorageBin:
    def __init__(self, bin_id: str, capacity_kg: int, accepts: frozenset[GradedCommodity], mixing: MixingRules,
                 opening_kg: int = 0, opening: GradedCommodity | None = None, in_service: bool = True):
        if capacity_kg <= 0:
            raise BinError(f"{bin_id}: capacity must be more than zero")
        if not 0 <= opening_kg <= capacity_kg:
            raise BinError(f"{bin_id}: opening stock {opening_kg} kg is outside 0..{capacity_kg} kg")
        if opening_kg > 0 and (opening is None or opening not in accepts):
            raise BinError(f"{bin_id}: opening stock needs a commodity and grade the bin accepts")
        self.id = bin_id
        self.capacity_kg = capacity_kg
        self.accepts = accepts
        self.mixing = mixing
        self.in_service = in_service
        self.tonnage_kg = opening_kg
        self._contents: GradedCommodity | None = opening if opening_kg > 0 else None
        self._incoming: dict[str, tuple[GradedCommodity, int]] = {}  # reservation id -> (grain, kg still expected)
        self._outgoing: dict[str, tuple[str, int]] = {}  # reservation id -> (commodity, kg still to dispatch)

    # ---- read-only state ----
    @property
    def incoming_kg(self) -> int:
        return sum(kg for _, kg in self._incoming.values())

    @property
    def outgoing_kg(self) -> int:
        return sum(kg for _, kg in self._outgoing.values())

    @property
    def free_space_kg(self) -> int:
        return self.capacity_kg - self.tonnage_kg - self.incoming_kg

    @property
    def available_stock_kg(self) -> int:
        return self.tonnage_kg - self.outgoing_kg

    @property
    def fill_fraction(self) -> Fraction:
        return Fraction(self.tonnage_kg, self.capacity_kg)

    def _identity_with(self, extra: list[GradedCommodity]) -> tuple[bool, GradedCommodity | None]:
        """Combine contents, pending incoming grain and `extra`. Returns (consistent, identity)."""
        identity = self._contents
        for grain in [g for g, _ in self._incoming.values()] + extra:
            if identity is None:
                identity = grain
                continue
            combined = self.mixing.combine(identity, grain)
            if combined is None:
                return False, identity
            identity = combined
        return True, identity

    @property
    def identity(self) -> GradedCommodity | None:
        """Commodity and grade of the contents, including grain already reserved to arrive; None if unassigned."""
        return self._identity_with([])[1]

    def snapshot(self) -> tuple:
        return (self.tonnage_kg, self._contents, tuple(sorted(self._incoming.items())),
                tuple(sorted(self._outgoing.items())), self.accepts, self.in_service)

    # ---- incoming ----
    def check_incoming(self, grain: GradedCommodity, kg: int) -> Refused | None:
        if not self.in_service:
            return Refused([Reason("OUT_OF_SERVICE", f"{self.id} is out of service")])
        reasons: list[Reason] = []
        if grain not in self.accepts:
            reasons.append(Reason("BIN_NOT_ALLOWED", f"{self.id} is not assigned to {grain.commodity} grade {grain.grade}"))
        consistent, combined = self._identity_with([grain])
        if not consistent:
            current = self.identity
            reasons.append(Reason("BIN_INCOMPATIBLE", f"{self.id} holds {current.commodity} grade {current.grade}; "
                                                      f"{grain.commodity} grade {grain.grade} cannot be added"))
        elif combined not in self.accepts and not any(r.code == "BIN_NOT_ALLOWED" for r in reasons):
            reasons.append(Reason("BIN_NOT_ALLOWED", f"{self.id} would become {combined.commodity} grade {combined.grade}, "
                                                     "which it is not assigned to"))
        if kg > self.free_space_kg:
            reasons.append(Reason("BIN_FULL", f"{self.id} has {self.free_space_kg} kg free, {kg} kg needed"))
        return Refused(reasons) if reasons else None

    def reserve_incoming(self, reservation_id: str, grain: GradedCommodity, kg: int) -> None:
        self._new_id(reservation_id)
        self._positive(kg)
        refused = self.check_incoming(grain, kg)
        if refused:
            raise refused
        self._incoming[reservation_id] = (grain, kg)

    def receive(self, reservation_id: str, kg: int) -> None:
        grain, expected = self._known(self._incoming, reservation_id)
        self._positive(kg)
        if kg > expected:
            raise BinError(f"{self.id}: {kg} kg delivered against {expected} kg reserved ({reservation_id})")
        self.tonnage_kg += kg
        self._contents = grain if self._contents is None else self.mixing.combine(self._contents, grain)
        if self._contents is None:
            raise BinError(f"{self.id}: incompatible grain received ({reservation_id})")
        if kg == expected:
            del self._incoming[reservation_id]
        else:
            self._incoming[reservation_id] = (grain, expected - kg)

    def has_incoming(self, reservation_id: str) -> bool:
        return reservation_id in self._incoming

    def release_incoming(self, reservation_id: str) -> None:
        """Cancel the rest of an incoming reservation (partial transfer, cancellation or failure)."""
        self._known(self._incoming, reservation_id)
        del self._incoming[reservation_id]

    # ---- outgoing ----
    def check_outgoing(self, commodity: str, kg: int) -> Refused | None:
        if not self.in_service:
            return Refused([Reason("OUT_OF_SERVICE", f"{self.id} is out of service")])
        reasons: list[Reason] = []
        if self._contents is not None and self._contents.commodity != commodity:
            reasons.append(Reason("BIN_INCOMPATIBLE", f"{self.id} holds {self._contents.commodity}, not {commodity}"))
        if kg > self.available_stock_kg:
            reasons.append(Reason("STOCK_SHORT", f"{self.id} has {self.available_stock_kg} kg uncommitted, {kg} kg needed"))
        return Refused(reasons) if reasons else None

    def reserve_outgoing(self, reservation_id: str, commodity: str, kg: int) -> None:
        self._new_id(reservation_id)
        self._positive(kg)
        refused = self.check_outgoing(commodity, kg)
        if refused:
            raise refused
        self._outgoing[reservation_id] = (commodity, kg)

    def dispatch(self, reservation_id: str, kg: int) -> None:
        commodity, committed = self._known(self._outgoing, reservation_id)
        self._positive(kg)
        if kg > committed:
            raise BinError(f"{self.id}: {kg} kg dispatched against {committed} kg committed ({reservation_id})")
        self.tonnage_kg -= kg
        if kg == committed:
            del self._outgoing[reservation_id]
        else:
            self._outgoing[reservation_id] = (commodity, committed - kg)
        if self.tonnage_kg == 0:
            self._contents = None

    # ---- process loss (step 18) ----
    def check_loss(self, kg: int, commodity: str | None = None) -> Refused | None:
        """A physical loss may take only uncommitted stock of the bin's contents (S6: refused in full otherwise)."""
        if self.tonnage_kg == 0:
            return Refused([Reason("BIN_EMPTY", f"{self.id} is empty")])
        if commodity is not None and self._contents is not None and self._contents.commodity != commodity:
            return Refused([Reason("BIN_INCOMPATIBLE", f"{self.id} holds {self._contents.commodity}, not {commodity}")])
        if kg > self.available_stock_kg:
            return Refused([Reason("STOCK_SHORT", f"{self.id} has {self.available_stock_kg} kg uncommitted, "
                                                  f"{kg} kg loss refused")])
        return None

    def remove_loss(self, kg: int, commodity: str | None = None) -> None:
        self._positive(kg)
        refused = self.check_loss(kg, commodity)
        if refused:
            raise refused
        self.tonnage_kg -= kg
        if self.tonnage_kg == 0:
            self._contents = None

    def has_outgoing(self, reservation_id: str) -> bool:
        return reservation_id in self._outgoing

    def release_outgoing(self, reservation_id: str) -> None:
        self._known(self._outgoing, reservation_id)
        del self._outgoing[reservation_id]

    # ---- assignment and availability ----
    def check_reassign(self, accepts: frozenset[GradedCommodity]) -> Refused | None:
        held = ([self._contents] if self._contents else []) + [g for g, _ in self._incoming.values()]
        identity = self.identity
        if any(g not in accepts for g in held) or (identity is not None and identity not in accepts):
            return Refused([Reason("BIN_INCOMPATIBLE", f"{self.id} holds or expects grain the new assignment does not allow")])
        return None

    def reassign(self, accepts: frozenset[GradedCommodity]) -> None:
        refused = self.check_reassign(accepts)
        if refused:
            raise refused
        self.accepts = accepts

    def set_in_service(self, in_service: bool) -> None:
        self.in_service = in_service

    # ---- invariants (independent of the methods above) ----
    def check_invariants(self) -> list[str]:
        problems = []
        if not 0 <= self.tonnage_kg <= self.capacity_kg:
            problems.append(f"{self.id}: tonnage {self.tonnage_kg} kg outside 0..{self.capacity_kg} kg")
        if self.tonnage_kg + self.incoming_kg > self.capacity_kg:
            problems.append(f"{self.id}: contents plus incoming reservations exceed capacity")
        if self.outgoing_kg > self.tonnage_kg:
            problems.append(f"{self.id}: more grain committed out than held")
        if (self.tonnage_kg == 0) != (self._contents is None):
            problems.append(f"{self.id}: contents identity does not match tonnage")
        if not self._identity_with([])[0]:
            problems.append(f"{self.id}: contents and incoming reservations are not compatible")
        return problems

    # ---- helpers ----
    def _new_id(self, reservation_id: str) -> None:
        if reservation_id in self._incoming or reservation_id in self._outgoing:
            raise BinError(f"{self.id}: reservation id {reservation_id} already in use")

    @staticmethod
    def _positive(kg: int) -> None:
        if type(kg) is not int or kg <= 0:
            raise BinError(f"quantity must be a positive whole number of kilograms, got {kg!r}")

    def _known(self, table: dict, reservation_id: str):
        if reservation_id not in table:
            raise BinError(f"{self.id}: unknown reservation {reservation_id}")
        return table[reservation_id]
