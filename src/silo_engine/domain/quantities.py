"""Grain quantities.

Policy: grain is held as whole **kilograms** (int). Inputs are decimal tonnes with at most three decimals;
anything finer is refused rather than rounded. Integer kilograms make material balance exact (no tolerance),
as CLAUDE.md §5 and ARCHITECTURE.md ('validated integer subunits') ask.
"""
from decimal import Decimal, InvalidOperation

KG_PER_TONNE = 1_000


class QuantityError(ValueError):
    pass


def tonnes_to_kg(tonnes: str | int | float | Decimal) -> int:
    if isinstance(tonnes, bool):
        raise QuantityError(f"{tonnes!r} is not a quantity")
    try:
        value = Decimal(str(tonnes)) if isinstance(tonnes, float) else Decimal(tonnes)  # type: ignore[arg-type]
    except (InvalidOperation, TypeError, ValueError):
        raise QuantityError(f"'{tonnes}' is not a number of tonnes") from None
    kg = value * KG_PER_TONNE
    if not kg.is_finite() or kg != kg.to_integral_value():
        raise QuantityError(f"{tonnes} t is more precise than one kilogram")
    if kg <= 0:
        raise QuantityError(f"{tonnes} t must be more than zero")
    return int(kg)


def format_tonnes(kg: int) -> str:
    """Kilograms -> '32.125 t' (trailing zeros dropped)."""
    text = f"{Decimal(kg) / KG_PER_TONNE:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text + " t"
