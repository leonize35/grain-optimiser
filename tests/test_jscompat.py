"""JavaScript-compatible helpers needed for exact parity with the prototype's messages and route ordering."""
from silo_engine.config.jscompat import js_number, js_round, locale_sort_key


def test_numbers_print_like_javascript():
    assert js_number(4500.0) == "4500"
    assert js_number(32.5) == "32.5"
    assert js_number(0) == "0"
    assert js_number(None) == "undefined"


def test_rounding_is_half_up_like_math_round():
    assert js_round(104.5) == 105
    assert js_round(2.5) == 3
    assert js_round(-2.5) == -2


def test_ordering_matches_browser_locale_compare():
    # Order observed from Chromium's String.prototype.localeCompare (see golden case b_mixed_case_ids).
    ids = ["BIN.A3", "bin-a1", "Bin_A2"]
    assert sorted(ids, key=locale_sort_key) == ["Bin_A2", "bin-a1", "BIN.A3"]
    assert sorted(["B4", "b B3", "B5"], key=locale_sort_key) == ["b B3", "B4", "B5"]
    assert sorted(["b", "B", "a"], key=locale_sort_key) == ["a", "b", "B"]
