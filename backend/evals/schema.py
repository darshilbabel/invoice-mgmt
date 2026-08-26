"""The fixture contract: what a hand-verified golden looks like, as a pydantic model.

One PDF, one `.expected.json`, same basename. This module is what makes a typo in a
hand-written golden fail at load with a field name, instead of reading as "that key
was absent" and quietly weakening a metric.

Money is a 2dp **string** everywhere, matching what `extraction.py` returns and what
`docs/conventions.md` § Money requires of the API. Every comparison in this suite is
then `==` on strings — no `Decimal` parsing, no float, no tolerance windows.

Path strings in `ambiguous` use the exact grammar `extraction.py` uses for
`low_confidence`, so calibration is a set operation with no translation layer:

    issue_date | due_date | notes | source_invoice_number | printed_total
    transactions.<zero-based index>.<description|quantity|unit_price>
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Mirrors extraction.SCHEMA's low_confidence documentation. Kept as a regex rather
# than an enum because the transactions form is open-ended in the index.
SCALAR_PATHS = frozenset(
    {"issue_date", "due_date", "notes", "source_invoice_number", "printed_total"}
)
_LINE_PATH = re.compile(r"^transactions\.\d+\.(description|quantity|unit_price)$")

_MONEY = re.compile(r"^-?\d+\.\d{2}$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_valid_path(path: str) -> bool:
    """True when `path` is a well-formed `low_confidence` field path."""
    return path in SCALAR_PATHS or bool(_LINE_PATH.match(path))


class Party(BaseModel):
    """One side of the invoice — the issuer or the party billed.

    All three fields matter, and not only for matching. The prompt's rule is
    stronger than "find the right party": *"never mix one party's name with the
    other party's contact details."* Testing that needs the issuer's email and
    address on record, so `metrics/direction.py` can assert the extracted ones
    are not them.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None


class LineItem(BaseModel):
    """One row of the invoice's table, as printed."""

    model_config = ConfigDict(extra="forbid")

    description: str
    quantity: str
    unit_price: str

    @field_validator("quantity", "unit_price")
    @classmethod
    def _two_decimal_places(cls, value: str) -> str:
        if not _MONEY.match(value):
            raise ValueError(
                f"{value!r} must be a 2dp string like '1.00' — extraction.to_money "
                "always quantizes to 2dp, so a golden written any other way can "
                "never match no matter how well the model reads the page"
            )
        return value


class ExpectedError(BaseModel):
    """For a fixture whose correct outcome is a refusal rather than a payload."""

    model_config = ConfigDict(extra="forbid")

    # Matches extraction.ExtractionError.reason.
    reason: str


class Expected(BaseModel):
    """A hand-verified golden for one invoice PDF."""

    model_config = ConfigDict(extra="forbid")

    # --- the two anti-anchoring guards -------------------------------------
    # A golden scaffolded from the model's own output and never checked would
    # score a perfect 1.0 while measuring nothing at all. dataset.py refuses to
    # load a fixture until both of these are satisfied. See dataset.py.
    verified: bool = Field(default=False, alias="_verified")
    note: str = Field(default="", alias="_note")

    source_pdf: str
    page_count: int

    issuer: Party
    bill_to: Party
    # "None is the correct answer here" — distinct from a golden that merely
    # forgot to fill bill_to in. extraction._normalise turns a nameless guess
    # into None, and on some invoices that is right.
    customer_absent: bool = False

    source_invoice_number: Optional[str] = None
    issue_date: Optional[str] = None
    due_date: Optional[str] = None

    printed_total: Optional[str] = None
    # Disambiguates the two reasons printed_total can be None: not printed on the
    # page (correct — extraction.py is explicit that it stays None rather than
    # becoming 0.00) versus printed but unreadable (a failure, which should also
    # show up in low_confidence). Without this key, a null printed_total in a
    # golden is untestable.
    printed_total_absent: bool = False

    line_items: list[LineItem] = Field(default_factory=list)
    # Descriptions that must NEVER appear as an extracted line item: the invoice's
    # own subtotal, tax and total rows. The prompt forbids importing them and doing
    # so inflates the invoice, but precision alone would blur it into a generic
    # "spurious row". This is the only way to catch it without an LLM.
    forbidden_descriptions: list[str] = Field(default_factory=list)

    # path -> why. A map rather than a list because the "why" is what makes this
    # hand-writable now and reviewable in six months. Drives calibration recall:
    # a field the model got wrong that was perfectly legible should have been
    # RIGHT, not flagged, so only paths listed here count toward recall.
    ambiguous: dict[str, str] = Field(default_factory=dict)

    # Verbatim page text that `notes` may draw on, for the grounding judge.
    notes_source_text: str = ""

    # Scaffold-computed, never hand-written: true when round-each-then-sum and
    # sum-then-round disagree on these line items. metrics/totals.py exists to
    # protect that rule, and it is untestable unless some fixture exercises the
    # divergence — so dataset.py warns when no loaded fixture has this set.
    rounding_divergent: bool = False

    expect_error: Optional[ExpectedError] = None

    @field_validator("issue_date", "due_date")
    @classmethod
    def _iso_date(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _ISO_DATE.match(value):
            raise ValueError(f"{value!r} must be an ISO date, YYYY-MM-DD")
        return value

    @field_validator("printed_total")
    @classmethod
    def _money(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _MONEY.match(value):
            raise ValueError(f"{value!r} must be a 2dp string like '6000.00'")
        return value

    @model_validator(mode="after")
    def _parties_differ(self) -> "Expected":
        """The two parties cannot be the same company.

        This closes the one hole the `issuer`-is-null guard leaves open. `scaffold.py`
        seeds `bill_to` from the extraction. If the model had confused the parties —
        returned the letterhead as the customer, the failure this suite most exists
        to catch — a reviewer who fills in `issuer` correctly but does not notice
        that `bill_to` now says the same company produces a golden that agrees with
        the bug. `metrics/direction.py` would then pass forever.

        An invoice a company sent to itself is not a thing. Rejecting it here costs
        nothing and makes that mistake impossible to save.
        """
        left = (self.issuer.name or "").strip().casefold()
        right = (self.bill_to.name or "").strip().casefold()
        if left and right and left == right:
            raise ValueError(
                f"issuer.name and bill_to.name are both {self.issuer.name!r}. An "
                "invoice is not addressed to the party that issued it — this "
                "usually means bill_to was left as the extractor's guess and the "
                "extractor confused the two parties, which is exactly the failure "
                "metrics/direction.py exists to catch. Read the PDF again."
            )
        return self

    @field_validator("ambiguous")
    @classmethod
    def _known_paths(cls, value: dict[str, str]) -> dict[str, str]:
        bad = sorted(p for p in value if not is_valid_path(p))
        if bad:
            raise ValueError(
                f"not valid low_confidence paths: {bad}. Use one of "
                f"{sorted(SCALAR_PATHS)} or 'transactions.<i>.<field>' — the "
                "grammar extraction.py's PROMPT tells the model to use. A path "
                "spelled any other way can never intersect what comes back, so "
                "calibration would silently score it as never-flagged."
            )
        return value

    def derived_total(self) -> Decimal:
        """The invoice total implied by these line items.

        Deliberately derived rather than a hand-written field: a hand-written total
        could disagree with the hand-written lines with no arbiter between them.
        Deriving it makes reconciliation a real three-way check — this, the same
        computation over what was extracted, and what is printed on the page.

        Rounds each line before summing, exactly as `Transaction.line_total` and
        `Invoice.total` do. See `docs/domain.md`: summing raw products and rounding
        once at the end is a different number.
        """
        from evals.money import line_total  # local import: keeps schema.py dependency-free

        return sum(
            (line_total(item.quantity, item.unit_price) for item in self.line_items),
            Decimal("0.00"),
        )


def parse_expected(raw: dict) -> Expected:
    """Validate a golden, letting pydantic's message name the offending field."""
    try:
        return Expected.model_validate(raw)
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(str(exc)) from exc
