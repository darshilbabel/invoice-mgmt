"""Regression guards on `extraction._normalise`. Not a measurement of the model.

Everything here is an invariant `_normalise` *constructs*, so it is true by
construction until someone edits those lines:

- `field_notes` keys are a subset of `low_confidence` — a dict comprehension.
- money is always a 2dp string — `to_money`'s `quantize`.
- dates are ISO or None — `to_date`'s regex gate.

They are worth guarding and they are not worth *scoring*. Folding them into the
deepeval suite would add a near-guaranteed 1.0 to every fixture and dilute the
metrics that can genuinely fail. So they live here: plain pytest, no judge, no
network, no cost, and framed as what they are.

The one genuinely model-facing conformance question — do the `low_confidence` paths
name fields that exist — is a scored metric instead. See `metrics/contract.py` for
why that one is different.

The `to_money` cases below are copied verbatim from
`docs/specs/2026-08-ocr-ingest.md` § Verification, which asks for exactly them and
says to re-run them by hand. This is that, automated.
"""

from __future__ import annotations

import re

import pytest

from billing.extraction import to_date, to_money
from evals.dataset import load
from evals.metrics.calibration import assert_normaliser_notes_unchanged

MONEY = re.compile(r"^-?\d+\.\d{2}$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- pure functions: no fixtures, no network -------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Rs 6,000.00", "6000.00"),  # currency symbol and thousands separator
        ("6000", "6000.00"),  # bare integer gains its cents
        ("$1,234.5", "1234.50"),
        ("2.5", "2.50"),
        ("", None),  # not zero — see extraction.to_money's docstring
        ("abc", None),
        ("-", None),
        (None, None),
    ],
)
def test_to_money_normalises_or_refuses(raw, expected):
    """A value that survives to_money is already in the form the API promises.

    The None cases matter as much as the parsing ones: an unreadable amount must
    NOT become 0.00 silently. `_normalise` turns None into a flagged field instead,
    which is what puts the amber marker on the review screen.
    """
    assert to_money(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-03-04", "2026-03-04"),
        ("20/07/2026", None),  # ambiguous day-first/month-first: dropped, then flagged
        ("March 4, 2026", None),
        ("", None),
        (None, None),
    ],
)
def test_to_date_passes_iso_and_drops_everything_else(raw, expected):
    assert to_date(raw) == expected


def test_normaliser_note_strings_are_unchanged():
    """The calibration metric identifies normaliser flags by their note text.

    If those strings are reworded in extraction.py and calibration.py is not
    updated, every normaliser-originated flag is silently miscounted as one the
    model raised, and calibration precision reads higher than it is — from that day
    on, with nothing connecting the two changes.
    """
    assert_normaliser_notes_unchanged()


# --- shape of a real payload: needs fixtures, but no network ----------------


def _payloads():
    return [
        (case.name, case.payload)
        for case in load()
        if case.outcome.ok and case.golden.expect_error is None
    ]


@pytest.fixture(scope="module")
def payloads():
    found = _payloads()
    if not found:
        pytest.skip("no fixtures — see evals/fixtures/README.md")
    return found


def test_money_fields_are_two_decimal_place_strings(payloads):
    """`docs/conventions.md`: money crosses the wire as a string, always.

    A bare number here means a DecimalField was skipped somewhere, which the spec
    calls out as the specific thing to watch for.
    """
    for name, payload in payloads:
        for index, row in enumerate(payload.get("transactions") or []):
            for field in ("quantity", "unit_price"):
                value = row[field]
                assert isinstance(value, str), f"{name}: transactions.{index}.{field}"
                assert MONEY.match(value), f"{name}: transactions.{index}.{field}={value!r}"
        total = payload.get("printed_total")
        if total is not None:
            assert isinstance(total, str) and MONEY.match(total), f"{name}: {total!r}"


def test_dates_are_iso_or_none(payloads):
    for name, payload in payloads:
        for field in ("issue_date", "due_date"):
            value = payload.get(field)
            assert value is None or ISO_DATE.match(value), f"{name}: {field}={value!r}"


def test_field_notes_only_describe_flagged_fields(payloads):
    """A note next to a field with no marker on it would be an orphan in the UI."""
    for name, payload in payloads:
        flags = set(payload.get("low_confidence") or [])
        notes = set(payload.get("field_notes") or {})
        assert notes <= flags, f"{name}: notes without flags: {sorted(notes - flags)}"


def test_every_documented_key_is_present(payloads):
    """The API contract in docs/architecture.md, as a shape assertion."""
    required = {
        "source_invoice_number",
        "issue_date",
        "due_date",
        "notes",
        "customer_guess",
        "transactions",
        "printed_total",
        "low_confidence",
        "field_notes",
        "page_count",
    }
    for name, payload in payloads:
        assert required <= set(payload), f"{name}: missing {sorted(required - set(payload))}"
