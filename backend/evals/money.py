"""The rounding rule, mirrored once.

`docs/domain.md` names this the single load-bearing rule of the system:

> Invoice totals are computed from the invoice's transactions, never stored as a
> flat field.

and the part of it that bites:

> `Round(..., 2)` goes *inside* the `Sum`. [...] Summing raw 4dp products and
> rounding once at the end gives a *different* answer: three lines of `0.25 x 0.50`
> are `0.39` per-line but `0.38` sum-first.

This module exists so the eval computes totals the way the application does, and so
that agreement is written down in exactly one place rather than re-derived in each
metric. `sum_then_round` is here for one reason only: `metrics/totals.py` computes
*both* and asserts the per-line-rounded one is what reconciles. A rule you only ever
compute the right way is a rule you cannot prove you are following.

Deliberately no import of `billing.models` — comparing against a mirror catches a
change to the application's rule, where calling the application's own function would
silently agree with whatever it now does.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENTS = Decimal("0.01")


def to_decimal(value: object) -> Decimal | None:
    """A Decimal, or None when the value is not a number.

    Not a re-implementation of `extraction.to_money`: this is for values that have
    *already* been through it (or come from a hand-written golden), so it does no
    currency-symbol stripping. Anything unparseable is None, never zero — a zero
    here would show up as a real disagreement in a total comparison.
    """
    if value is None:
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def line_total(quantity: object, unit_price: object) -> Decimal:
    """One line's total, quantized to cents — mirrors `Transaction.line_total`.

    Unparseable inputs count as zero for this line rather than raising, because a
    payload containing one is already being flagged elsewhere (extraction._normalise
    substitutes "0.00" and adds the path to low_confidence). Raising here would
    abort a total comparison that the line-item metrics are better placed to report.
    """
    qty = to_decimal(quantity) or Decimal("0")
    price = to_decimal(unit_price) or Decimal("0")
    return (qty * price).quantize(CENTS, rounding=ROUND_HALF_UP)


def round_then_sum(lines) -> Decimal:
    """Round each line to cents, then add. **This is the correct rule.**"""
    return sum(
        (line_total(row.get("quantity"), row.get("unit_price")) for row in lines),
        Decimal("0.00"),
    )


def sum_then_round(lines) -> Decimal:
    """Add raw products, then round once. **Wrong on purpose** — see the docstring.

    Only `metrics/totals.py` should call this, and only to demonstrate that it
    differs. Never use it to compute a total anyone will see.
    """
    total = Decimal("0")
    for row in lines:
        qty = to_decimal(row.get("quantity")) or Decimal("0")
        price = to_decimal(row.get("unit_price")) or Decimal("0")
        total += qty * price
    return total.quantize(CENTS, rounding=ROUND_HALF_UP)


def money_str(value: Decimal) -> str:
    """A 2dp string, the form money takes everywhere it crosses a boundary."""
    return str(value.quantize(CENTS, rounding=ROUND_HALF_UP))
