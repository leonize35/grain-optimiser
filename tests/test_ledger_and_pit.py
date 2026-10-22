"""Reservation ledger (atomic all-or-nothing claims) and the hopper pit model (R2, A3, A4).

Quantities in kilograms, times in milliseconds; t() and hm()/m() keep the numbers readable. Expected values are
hand-computed in comments.
"""
from fractions import Fraction

import pytest

from silo_engine.domain.storage import GradedCommodity, MixingRules, StorageBin
from silo_engine.sim.ledger import BinIncomingClaim, LaneClaim, LedgerError, PitSpaceClaim, ReservationLedger, SegmentClaim
from silo_engine.sim.pit import Lot, Pit
from silo_engine.sim.time import hm, m

YM = GradedCommodity("YM", "*")
WM = GradedCommodity("WM", "*")


def t(tonnes):
    return round(tonnes * 1000)


def make_pit(level=0, grain=YM, admission="full_load_space"):
    lots = [Lot("L0", None, grain, t(level), 0)] if level else []
    return Pit("H1", capacity_kg=t(60), rate_tph=Fraction(200), admission=admission, accepts={"YM", "WM"}, lots=lots)


def make_ledger(pit=None, bin_free=1000, segment_capacity=1):
    b = StorageBin("B1", capacity_kg=t(bin_free), accepts=frozenset({YM, WM}), mixing=MixingRules([]))
    return ReservationLedger(lanes={"WB1#0", "H1:tip"}, segments={"C1": segment_capacity, "E1": segment_capacity},
                             pits={"H1": pit or make_pit()}, bins={"B1": b}), b


# ---------------- pit ----------------

def test_pit_level_falls_continuously_while_draining():
    # 40 t in the pit; drain 40 t at 200 t/h from 07:00 -> 12 min. After 3 min, 10 t gone: 30 t left, 30 t free.
    p = make_pit(level=40)
    p.start_drain(t(40), hm("07:00"), m(12))
    assert p.level_at(hm("07:03")) == t(30)
    assert p.free_space_at(hm("07:03")) == t(30)
    assert p.level_at(hm("07:12")) == 0


def test_time_until_space_for_a_load_is_exact():
    # Need 30 t free in a 60 t pit holding 40 t: 10 t must drain at 200 t/h = 3 min -> 07:03.
    p = make_pit(level=40)
    p.start_drain(t(40), hm("07:00"), m(12))
    assert p.time_space_available(hm("07:00"), t(30)) == hm("07:03")
    assert p.time_space_available(hm("07:00"), t(15)) == hm("07:00")  # 20 t free already
    # Space only arrives after this drain ends if the need exceeds what the drain removes.
    assert p.time_space_available(hm("07:00"), t(61)) is None


def test_finishing_a_drain_removes_grain_from_the_head_lot():
    p = make_pit(level=40)
    p.start_drain(t(25), hm("07:00"), m(7.5))
    p.finish_drain(hm("07:07:30"))
    assert [(lot.id, lot.kg) for lot in p.lots] == [("L0", t(15))]
    assert p.draining is None


def test_full_load_space_rule():
    p = make_pit(level=40)  # 20 t free
    assert [r.code for r in p.check_claim(hm("07:00"), YM, t(30))] == ["PIT_SPACE"]
    assert p.check_claim(hm("07:00"), YM, t(20)) == []


def test_empty_pit_rule_needs_a_completely_empty_pit():
    p = make_pit(level=1, admission="empty_pit")
    assert [r.code for r in p.check_claim(hm("07:00"), YM, t(10))] == ["PIT_SPACE"]
    assert make_pit(admission="empty_pit").check_claim(hm("07:00"), YM, t(10)) == []


def test_pit_holds_one_commodity_at_a_time():
    # A4: white maize cannot be tipped onto yellow maize, even with space available.
    p = make_pit(level=10)
    assert [r.code for r in p.check_claim(hm("07:00"), WM, t(10))] == ["PIT_INCOMPATIBLE"]


def test_claim_becomes_a_lot_when_tipping_ends():
    p = make_pit()
    p.claim("R1", YM, t(30))
    assert p.free_space_at(0) == t(30)
    p.claim_to_lot("R1", Lot("L-T1", "T1", YM, t(30), hm("07:06")))
    assert p.claims == {} and p.level_at(hm("07:06")) == t(30)
    assert p.check_invariants(hm("07:06")) == []


# ---------------- ledger ----------------

def test_route_reservation_is_all_or_nothing():
    # Bin has only 20 t free: a 30 t claim on C1, E1 and B1 fails and leaves C1/E1 free.
    ledger, b = make_ledger(bin_free=20)
    before = ledger.snapshot()
    reasons = ledger.try_reserve("X1", [SegmentClaim("C1", YM), SegmentClaim("E1", YM), BinIncomingClaim("B1", YM, t(30))], 0)
    assert [r.code for r in reasons] == ["BIN_FULL"]
    assert ledger.snapshot() == before
    assert ledger.try_reserve("X2", [SegmentClaim("C1", YM), SegmentClaim("E1", YM), BinIncomingClaim("B1", YM, t(20))], 0) == []
    assert b.incoming_kg == t(20)


def test_release_frees_every_claim():
    ledger, b = make_ledger()
    ledger.try_reserve("X1", [SegmentClaim("C1", YM), SegmentClaim("E1", YM), BinIncomingClaim("B1", YM, t(30))], 0)
    ledger.release("X1", m(9), "cancelled")
    assert ledger.segment_streams("C1") == [] and b.incoming_kg == 0
    assert ledger.check_invariants(m(9)) == []


def test_exclusive_segment_refuses_a_second_stream():
    ledger, _ = make_ledger()
    ledger.try_reserve("X1", [SegmentClaim("E1", YM)], 0)
    assert [r.code for r in ledger.try_reserve("X2", [SegmentClaim("E1", YM)], 0)] == ["EQUIPMENT_BUSY"]


def test_shared_segment_allows_same_commodity_but_locks_out_others():
    # Capacity 2 is for build step 4; the commodity lock is enforced already.
    ledger, _ = make_ledger(segment_capacity=2)
    ledger.try_reserve("X1", [SegmentClaim("E1", YM)], 0)
    assert [r.code for r in ledger.try_reserve("X2", [SegmentClaim("E1", WM)], 0)] == ["COMMODITY_LOCK"]
    assert ledger.try_reserve("X3", [SegmentClaim("E1", YM)], 0) == []


def test_lane_and_pit_space_are_claimed_together():
    ledger, _ = make_ledger(pit=make_pit(level=40))  # 20 t free
    assert [r.code for r in ledger.try_reserve("T1", [LaneClaim("H1:tip"), PitSpaceClaim("H1", YM, t(30))], 0)] == ["PIT_SPACE"]
    assert ledger.lane_free("H1:tip")  # the lane was not taken
    assert ledger.try_reserve("T2", [LaneClaim("H1:tip"), PitSpaceClaim("H1", YM, t(20))], 0) == []
    assert not ledger.lane_free("H1:tip")


def test_segment_remembers_the_last_commodity_it_carried():
    ledger, _ = make_ledger()
    ledger.try_reserve("X1", [SegmentClaim("E1", YM)], 0)
    ledger.release("X1", m(9), "completed")
    assert ledger.last_grain("E1") == YM


def test_ledger_misuse_is_an_error():
    ledger, _ = make_ledger()
    ledger.try_reserve("X1", [LaneClaim("WB1#0")], 0)
    with pytest.raises(LedgerError):
        ledger.try_reserve("X1", [LaneClaim("H1:tip")], 0)  # id reused
    with pytest.raises(LedgerError):
        ledger.release("NOPE", 0, "completed")
    with pytest.raises(LedgerError):
        ledger.try_reserve("X9", [LaneClaim("UNKNOWN")], 0)


def test_log_records_every_reservation_and_release():
    ledger, _ = make_ledger()
    ledger.try_reserve("X1", [LaneClaim("WB1#0")], hm("07:00"))
    ledger.release("X1", hm("07:02"), "completed")
    assert [(e.time, e.op, e.reservation_id) for e in ledger.log] == [
        (hm("07:00"), "reserve", "X1"), (hm("07:02"), "release:completed", "X1")]
