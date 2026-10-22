"""Atomic reservation ledger (docs/ENGINE_INTERFACES.md §3).

Every finite resource a piece of work needs is claimed through the ledger, in one step:
all claims are checked first; only if every check passes are they all taken. A refusal changes nothing and
returns the reasons. `release` frees every claim of a reservation (completed, cancelled or failed).

Claim types:
- `LaneClaim`        one lane of a station (e.g. ``WB1#0``) or a hopper's tipping lane (``H1:tip``);
- `SegmentClaim`     one stream on a conveyor or elevator, with its commodity (commodity lock, R1);
- `PitSpaceClaim`    space in a hopper pit for a truck that is tipping (R2);
- `BinIncomingClaim` space in a storage bin for grain on its way (R7).

All claims and releases are written to `log` for independent checking.
"""
from dataclasses import dataclass, field

from ..domain.storage import GradedCommodity, StorageBin
from .dispatcher import WaitReason
from .pit import Pit


@dataclass(frozen=True)
class LaneClaim:
    resource: str


@dataclass(frozen=True)
class SegmentClaim:
    equipment_id: str
    grain: GradedCommodity


@dataclass(frozen=True)
class PitSpaceClaim:
    pit_id: str
    grain: GradedCommodity
    kg: int


@dataclass(frozen=True)
class BinIncomingClaim:
    bin_id: str
    grain: GradedCommodity
    kg: int


Claim = LaneClaim | SegmentClaim | PitSpaceClaim | BinIncomingClaim


@dataclass(frozen=True)
class LedgerEntry:
    time: int
    op: str
    reservation_id: str
    claims: tuple


class LedgerError(RuntimeError):
    pass


@dataclass
class _Segment:
    capacity: int
    streams: dict[str, GradedCommodity] = field(default_factory=dict)  # reservation id -> grain
    last: GradedCommodity | None = None


class ReservationLedger:
    def __init__(self, lanes: set[str], segments: dict[str, int], pits: dict[str, Pit], bins: dict[str, StorageBin]):
        self._lanes: dict[str, str | None] = {lane: None for lane in lanes}
        self._segments = {sid: _Segment(cap) for sid, cap in segments.items()}
        self.pits = pits
        self.bins = bins
        self._held: dict[str, tuple[Claim, ...]] = {}
        self.log: list[LedgerEntry] = []

    # ---- queries ----
    def lane_free(self, lane: str) -> bool:
        return self._lanes[lane] is None

    def segment_streams(self, segment_id: str) -> list[GradedCommodity]:
        return list(self._segments[segment_id].streams.values())

    def last_grain(self, segment_id: str) -> GradedCommodity | None:
        return self._segments[segment_id].last

    def holds(self, reservation_id: str) -> tuple[Claim, ...]:
        return self._held[reservation_id]

    def snapshot(self) -> tuple:
        return (tuple(sorted(self._lanes.items(), key=lambda x: x[0])),
                tuple((sid, tuple(sorted(s.streams.items())), s.last) for sid, s in sorted(self._segments.items())),
                tuple((pid, tuple(sorted(p.claims.items()))) for pid, p in sorted(self.pits.items())),
                tuple((bid, b.snapshot()) for bid, b in sorted(self.bins.items())),
                tuple(sorted(self._held)))

    # ---- checking ----
    def _check_one(self, claim: Claim, now: int) -> list[WaitReason]:
        if isinstance(claim, LaneClaim):
            if claim.resource not in self._lanes:
                raise LedgerError(f"Unknown lane {claim.resource}")
            holder = self._lanes[claim.resource]
            return [] if holder is None else [WaitReason("EQUIPMENT_BUSY", claim.resource, f"{claim.resource} busy")]
        if isinstance(claim, SegmentClaim):
            if claim.equipment_id not in self._segments:
                raise LedgerError(f"Unknown segment {claim.equipment_id}")
            seg = self._segments[claim.equipment_id]
            if any(g != claim.grain for g in seg.streams.values()):
                return [WaitReason("COMMODITY_LOCK", claim.equipment_id,
                                   f"{claim.equipment_id} is carrying other grain")]
            if len(seg.streams) >= seg.capacity:
                return [WaitReason("EQUIPMENT_BUSY", claim.equipment_id, f"{claim.equipment_id} busy")]
            return []
        if isinstance(claim, PitSpaceClaim):
            return self.pits[claim.pit_id].check_claim(now, claim.grain, claim.kg)
        if isinstance(claim, BinIncomingClaim):
            refused = self.bins[claim.bin_id].check_incoming(claim.grain, claim.kg)
            return [] if refused is None else [WaitReason(r.code, claim.bin_id, r.detail) for r in refused.reasons]
        raise LedgerError(f"Unknown claim {claim!r}")

    def check(self, claims: list[Claim], now: int) -> list[WaitReason]:
        reasons: list[WaitReason] = []
        for claim in claims:
            reasons.extend(self._check_one(claim, now))
        return reasons

    # ---- reserving and releasing ----
    def try_reserve(self, reservation_id: str, claims: list[Claim], now: int) -> list[WaitReason]:
        if reservation_id in self._held:
            raise LedgerError(f"Reservation id {reservation_id} already in use")
        reasons = self.check(claims, now)
        if reasons:
            return reasons
        for claim in claims:
            if isinstance(claim, LaneClaim):
                self._lanes[claim.resource] = reservation_id
            elif isinstance(claim, SegmentClaim):
                self._segments[claim.equipment_id].streams[reservation_id] = claim.grain
            elif isinstance(claim, PitSpaceClaim):
                self.pits[claim.pit_id].claim(reservation_id, claim.grain, claim.kg)
            elif isinstance(claim, BinIncomingClaim):
                self.bins[claim.bin_id].reserve_incoming(reservation_id, claim.grain, claim.kg)
        self._held[reservation_id] = tuple(claims)
        self.log.append(LedgerEntry(now, "reserve", reservation_id, tuple(claims)))
        return []

    def release(self, reservation_id: str, now: int, outcome: str) -> None:
        if reservation_id not in self._held:
            raise LedgerError(f"Unknown reservation {reservation_id}")
        claims = self._held.pop(reservation_id)
        for claim in claims:
            if isinstance(claim, LaneClaim):
                self._lanes[claim.resource] = None
            elif isinstance(claim, SegmentClaim):
                seg = self._segments[claim.equipment_id]
                del seg.streams[reservation_id]
                if outcome == "completed":
                    seg.last = claim.grain
            elif isinstance(claim, PitSpaceClaim):
                self.pits[claim.pit_id].release_claim(reservation_id)  # no-op if it already became a lot
            elif isinstance(claim, BinIncomingClaim):
                b = self.bins[claim.bin_id]
                if b.has_incoming(reservation_id):  # unused remainder of a partial or cancelled transfer
                    b.release_incoming(reservation_id)
        self.log.append(LedgerEntry(now, f"release:{outcome}", reservation_id, claims))

    # ---- independent checks ----
    def check_invariants(self, now: int) -> list[str]:
        problems = []
        for lane, holder in self._lanes.items():
            if holder is not None and holder not in self._held:
                problems.append(f"{lane} held by unknown reservation {holder}")
        for sid, seg in self._segments.items():
            if len(seg.streams) > seg.capacity:
                problems.append(f"{sid}: {len(seg.streams)} streams on capacity {seg.capacity}")
            if len(set(seg.streams.values())) > 1:
                problems.append(f"{sid}: different grain on the same equipment")
        for pit in self.pits.values():
            problems.extend(pit.check_invariants(now))
        for b in self.bins.values():
            problems.extend(b.check_invariants())
        return problems
