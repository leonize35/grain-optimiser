"""Storage bin rules (R7 in docs/DOMAIN_DECISIONS.md), with grade mixing (R4).

All quantities are whole kilograms; t(x) converts tonnes for readability. Every expected value is hand-computed.
Every test ends by asserting the bin's invariants hold.
"""
from fractions import Fraction

import pytest

from silo_engine.domain.storage import BinError, GradedCommodity, MixingRules, Refused, StorageBin


def t(tonnes: float | int) -> int:
    return round(tonnes * 1000)


YM1 = GradedCommodity("YM", "1")
YM2 = GradedCommodity("YM", "2")
WM1 = GradedCommodity("WM", "1")

NO_MIXING = MixingRules([])
YM_1_2_MIX = MixingRules([("YM", {"1", "2"}, "2")])  # grades 1 and 2 may share a bin; the mixture is grade 2


def bin_with(accepts=(YM1, YM2, WM1), mixing=NO_MIXING, capacity=1000, stock=0, stock_grade=YM1) -> StorageBin:
    return StorageBin("B1", capacity_kg=t(capacity), accepts=frozenset(accepts), mixing=mixing,
                      opening_kg=t(stock), opening=stock_grade if stock else None)


def codes(refused: Refused) -> list[str]:
    return [r.code for r in refused.reasons]


def test_opening_state_reports_tonnage_fill_identity_and_space():
    b = bin_with(stock=400)  # 400 t yellow maize grade 1 in a 1000 t bin
    assert b.tonnage_kg == t(400)
    assert b.fill_fraction == Fraction(2, 5)  # 40 %
    assert b.identity == YM1
    assert b.free_space_kg == t(600)
    assert b.available_stock_kg == t(400)
    assert b.check_invariants() == []


def test_incoming_reservation_holds_space_until_grain_is_received():
    b = bin_with(stock=400)
    b.reserve_incoming("R1", YM1, t(30))
    assert (b.tonnage_kg, b.incoming_kg, b.free_space_kg) == (t(400), t(30), t(570))
    b.receive("R1", t(30))
    assert (b.tonnage_kg, b.incoming_kg, b.free_space_kg) == (t(430), 0, t(570))
    assert b.check_invariants() == []


def test_partial_delivery_then_release_returns_unused_space():
    b = bin_with(stock=400)
    b.reserve_incoming("R1", YM1, t(30))
    b.receive("R1", t(20))
    assert (b.tonnage_kg, b.incoming_kg) == (t(420), t(10))
    b.release_incoming("R1")
    assert (b.tonnage_kg, b.incoming_kg, b.free_space_kg) == (t(420), 0, t(580))
    assert b.check_invariants() == []


def test_different_commodity_is_refused_and_nothing_changes():
    b = bin_with(stock=400)
    before = b.snapshot()
    result = b.check_incoming(WM1, t(30))
    assert codes(result) == ["BIN_INCOMPATIBLE"]
    with pytest.raises(Refused):
        b.reserve_incoming("R1", WM1, t(30))
    assert b.snapshot() == before


def test_other_grade_is_refused_without_a_mixing_rule():
    b = bin_with(stock=400)
    assert codes(b.check_incoming(YM2, t(30))) == ["BIN_INCOMPATIBLE"]


def test_mixing_rule_lets_grades_share_and_classifies_the_mixture():
    b = bin_with(mixing=YM_1_2_MIX, stock=400, stock_grade=YM2)  # bin holds grade 2
    b.reserve_incoming("R1", YM1, t(30))  # grade 1 may join: mixture is grade 2
    b.receive("R1", t(30))
    assert b.identity == YM2
    assert b.tonnage_kg == t(430)
    assert b.check_invariants() == []


def test_mixing_into_a_bin_that_does_not_accept_the_resulting_grade_is_refused():
    # Bin accepts grade 1 only. Grade-1 contents + grade-2 grain would make grade 2, which the bin does not accept.
    b = bin_with(accepts=(YM1,), mixing=YM_1_2_MIX, stock=400)
    assert codes(b.check_incoming(YM2, t(30))) == ["BIN_NOT_ALLOWED"]


def test_grain_the_bin_is_not_assigned_to_is_refused():
    b = bin_with(accepts=(YM1,))
    assert codes(b.check_incoming(WM1, t(30))) == ["BIN_NOT_ALLOWED"]


def test_space_limit_is_exact_to_the_kilogram():
    b = bin_with(stock=400)
    assert codes(b.check_incoming(YM1, t(600) + 1)) == ["BIN_FULL"]
    b.reserve_incoming("R1", YM1, t(600))
    assert b.free_space_kg == 0
    assert codes(b.check_incoming(YM1, 1)) == ["BIN_FULL"]
    assert b.check_invariants() == []


def test_pending_reservation_fixes_identity_of_an_empty_bin():
    # Prevents two commodities being reserved into an empty bin before either arrives (segregation).
    b = bin_with()
    assert b.identity is None
    b.reserve_incoming("R1", YM1, t(30))
    assert b.identity == YM1
    assert codes(b.check_incoming(WM1, t(30))) == ["BIN_INCOMPATIBLE"]
    assert b.check_invariants() == []


def test_outgoing_commitment_reserves_stock_and_dispatch_removes_it():
    b = bin_with(stock=400)
    b.reserve_outgoing("L1", "YM", t(34))
    assert (b.tonnage_kg, b.outgoing_kg, b.available_stock_kg) == (t(400), t(34), t(366))
    b.dispatch("L1", t(34))
    assert (b.tonnage_kg, b.outgoing_kg, b.available_stock_kg) == (t(366), 0, t(366))
    assert b.check_invariants() == []


def test_outgoing_beyond_available_stock_or_of_another_commodity_is_refused():
    b = bin_with(stock=400)
    b.reserve_outgoing("L1", "YM", t(380))
    assert codes(b.check_outgoing("YM", t(21))) == ["STOCK_SHORT"]  # only 20 t uncommitted
    assert codes(b.check_outgoing("WM", t(10))) == ["BIN_INCOMPATIBLE"]


def test_emptying_the_bin_clears_its_identity():
    b = bin_with(stock=30)
    b.reserve_outgoing("L1", "YM", t(30))
    b.dispatch("L1", t(30))
    assert b.tonnage_kg == 0 and b.identity is None
    b.reserve_incoming("R1", WM1, t(30))  # now white maize is allowed
    assert b.identity == WM1
    assert b.check_invariants() == []


def test_reassignment_cannot_overwrite_existing_inventory():
    b = bin_with(stock=400)
    assert codes(b.check_reassign(frozenset({WM1}))) == ["BIN_INCOMPATIBLE"]
    with pytest.raises(Refused):
        b.reassign(frozenset({WM1}))
    assert b.accepts == frozenset({YM1, YM2, WM1})


def test_reassignment_cannot_contradict_a_pending_reservation():
    b = bin_with()
    b.reserve_incoming("R1", YM1, t(30))
    assert codes(b.check_reassign(frozenset({WM1}))) == ["BIN_INCOMPATIBLE"]


def test_reassignment_of_an_empty_bin_applies_to_future_grain():
    b = bin_with(accepts=(YM1,))
    b.reassign(frozenset({WM1}))
    assert codes(b.check_incoming(YM1, t(1))) == ["BIN_NOT_ALLOWED"]
    b.reserve_incoming("R1", WM1, t(1))
    assert b.check_invariants() == []


def test_out_of_service_bin_takes_no_new_reservations_but_honours_existing_ones():
    """ASSUMPTION A8 (docs/DOMAIN_DECISIONS.md): existing reservations are honoured."""
    b = bin_with(stock=400)
    b.reserve_incoming("R1", YM1, t(30))
    b.set_in_service(False)
    assert codes(b.check_incoming(YM1, t(1))) == ["OUT_OF_SERVICE"]
    assert codes(b.check_outgoing("YM", t(1))) == ["OUT_OF_SERVICE"]
    b.receive("R1", t(30))
    assert b.tonnage_kg == t(430)
    assert b.check_invariants() == []


def test_misuse_is_an_engine_error_not_a_refusal():
    b = bin_with(stock=400)
    b.reserve_incoming("R1", YM1, t(30))
    with pytest.raises(BinError):
        b.receive("R1", t(31))  # more than reserved
    with pytest.raises(BinError):
        b.receive("NOPE", 1)  # unknown reservation
    with pytest.raises(BinError):
        b.reserve_incoming("R1", YM1, 1)  # reservation id reused
    with pytest.raises(BinError):
        b.reserve_incoming("R2", YM1, 0)  # zero quantity


def test_opening_stock_must_be_consistent():
    with pytest.raises(BinError):
        StorageBin("B9", capacity_kg=t(100), accepts=frozenset({YM1}), mixing=NO_MIXING, opening_kg=t(101), opening=YM1)
    with pytest.raises(BinError):
        StorageBin("B9", capacity_kg=t(100), accepts=frozenset({YM1}), mixing=NO_MIXING, opening_kg=t(10), opening=WM1)
    with pytest.raises(BinError):
        StorageBin("B9", capacity_kg=t(100), accepts=frozenset({YM1}), mixing=NO_MIXING, opening_kg=t(10), opening=None)


def test_mixing_rules_combine_only_listed_grades_of_the_same_commodity():
    assert YM_1_2_MIX.combine(YM1, YM1) == YM1
    assert YM_1_2_MIX.combine(YM1, YM2) == YM2
    assert YM_1_2_MIX.combine(YM2, YM1) == YM2
    assert YM_1_2_MIX.combine(YM1, WM1) is None
    assert YM_1_2_MIX.combine(YM1, GradedCommodity("YM", "3")) is None
    assert NO_MIXING.combine(YM1, YM2) is None
