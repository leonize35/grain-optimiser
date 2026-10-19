"""Simulation time.

Policy: the clock counts whole **milliseconds** from midnight at the start of the first simulated day.
Integer time makes "simultaneous" exact (no floating-point near-ties) and keeps traces hand-checkable.
Conversions refuse values that are not a whole number of milliseconds instead of silently rounding.
Random durations (later steps) will be rounded to the nearest millisecond at the point they are drawn.
"""
import re
from decimal import Decimal, InvalidOperation

MS_PER_SECOND = 1_000
MS_PER_MINUTE = 60_000
MS_PER_HOUR = 3_600_000
MS_PER_DAY = 86_400_000

_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


class TimeFormatError(ValueError):
    pass


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise TimeFormatError(f"{value!r} is not a time")
    try:
        # str() of a float gives its shortest decimal form, so 390.25 stays exactly 390.25.
        return Decimal(str(value)) if isinstance(value, float) else Decimal(value)  # type: ignore[arg-type]
    except (InvalidOperation, TypeError, ValueError):
        raise TimeFormatError(f"{value!r} is not a number of minutes") from None


def m(minutes: int | Decimal | str) -> int:
    """Minutes -> milliseconds, exactly."""
    ms = _decimal(minutes) * MS_PER_MINUTE
    if ms != ms.to_integral_value():
        raise TimeFormatError(f"{minutes} minutes is not a whole number of milliseconds")
    return int(ms)


def hm(clock: str) -> int:
    """'HH:MM' or 'HH:MM:SS' on the first day -> milliseconds."""
    match = _CLOCK.match(clock.strip())
    if not match:
        raise TimeFormatError(f"'{clock}' is not a clock time like 07:30")
    h, mi, s = int(match[1]), int(match[2]), int(match[3] or 0)
    if h > 23 or mi > 59 or s > 59:
        raise TimeFormatError(f"'{clock}' is not a valid clock time")
    return h * MS_PER_HOUR + mi * MS_PER_MINUTE + s * MS_PER_SECOND


def parse_time(value: str | int | float | Decimal) -> int:
    """A clock string ('07:30') or a number of minutes from midnight (390, '390.25') -> milliseconds."""
    if isinstance(value, str) and ":" in value:
        return hm(value)
    ms = m(value)  # type: ignore[arg-type]
    if ms < 0:
        raise TimeFormatError(f"{value} is before the start of the simulation")
    return ms


def format_clock(ms: int) -> str:
    """Milliseconds -> '07:05', '07:05:30', or 'day 2 00:01' after the first midnight."""
    day, rest = divmod(ms, MS_PER_DAY)
    h, rest = divmod(rest, MS_PER_HOUR)
    mi, rest = divmod(rest, MS_PER_MINUTE)
    s, milli = divmod(rest, MS_PER_SECOND)
    text = f"{h:02d}:{mi:02d}"
    if s or milli:
        text += f":{s:02d}" + (f".{milli:03d}" if milli else "")
    return f"day {day + 1} {text}" if day else text
