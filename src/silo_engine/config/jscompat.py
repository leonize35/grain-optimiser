"""Helpers that reproduce JavaScript behaviour the prototype's output depends on.

They exist only to keep exact parity with prototype engine v0.2.0 (messages and route tie-break order).
"""
import math

# Punctuation order of the ICU root collation used by browsers' String.prototype.localeCompare.
# Whitespace sorts first, then punctuation in this order, then digits, then letters (case-insensitive at the
# primary level; lowercase before uppercase at the tertiary level).
_PUNCTUATION = " _-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"


def js_number(x: float | int | None) -> str:
    """Format a number the way JavaScript string concatenation does (4500.0 -> '4500', None -> 'undefined')."""
    if x is None:
        return "undefined"
    if isinstance(x, float) and x.is_integer() and abs(x) < 1e21:
        return str(int(x))
    return repr(x) if isinstance(x, float) else str(x)


def js_str(x: object) -> str:
    """String conversion used when the prototype concatenates a possibly missing value."""
    if x is None:
        return "undefined"
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return js_number(x)
    return str(x)


def js_round(x: float) -> int:
    """Math.round: halves round towards +infinity."""
    return math.floor(x + 0.5)


def _primary(ch: str) -> tuple[int, int]:
    i = _PUNCTUATION.find(ch)
    if i >= 0:
        return (0, i)
    if ch.isdigit():
        return (1, ord(ch))
    if ch.isalpha():
        return (2, ord(ch.lower()))
    return (3, ord(ch))


def locale_sort_key(s: str) -> tuple[tuple[tuple[int, int], ...], tuple[int, ...]]:
    """Sort key approximating Chromium's default localeCompare for ASCII identifiers.

    Verified against the browser for letters, digits, space, '_', '-', ',' and '.' (golden case b_mixed_case_ids).
    """
    return tuple(_primary(c) for c in s), tuple(1 if c.isupper() else 0 for c in s)
