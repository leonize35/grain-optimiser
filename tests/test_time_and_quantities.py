"""Time and quantity conversions used by scripted inputs. All expected values are hand-computed."""
from decimal import Decimal

import pytest

from silo_engine.domain.quantities import QuantityError, format_tonnes, tonnes_to_kg
from silo_engine.sim.time import MS_PER_MINUTE, TimeFormatError, format_clock, hm, m, parse_time


def test_minutes_and_clock_times_convert_to_milliseconds():
    assert MS_PER_MINUTE == 60_000
    assert m(1) == 60_000
    assert m(Decimal("0.5")) == 30_000
    assert hm("07:30") == 450 * 60_000 == 27_000_000
    assert hm("07:30:15") == 27_015_000
    assert hm("00:00") == 0


def test_parse_time_accepts_clock_strings_and_minute_numbers():
    assert parse_time("06:00") == m(360)
    assert parse_time(390) == m(390)
    assert parse_time("390.25") == m(390) + 15_000


def test_bad_times_are_refused():
    for bad in ["7h30", "24:00", "07:60", "-5", "abc", 1.0000001]:
        with pytest.raises(TimeFormatError):
            parse_time(bad)


def test_format_clock_for_messages():
    assert format_clock(hm("07:05")) == "07:05"
    assert format_clock(hm("07:05:30")) == "07:05:30"
    assert format_clock(hm("23:59") + m(2)) == "day 2 00:01"


def test_tonnes_convert_exactly_to_kilograms():
    assert tonnes_to_kg("32.125") == 32_125
    assert tonnes_to_kg(30) == 30_000
    assert tonnes_to_kg(Decimal("0.001")) == 1
    assert format_tonnes(32_125) == "32.125 t"


def test_tonnes_with_more_than_kilogram_precision_or_not_positive_are_refused():
    for bad in ["32.1255", "0", "-1", "abc", 0.1 + 0.2]:
        with pytest.raises(QuantityError):
            tonnes_to_kg(bad)
