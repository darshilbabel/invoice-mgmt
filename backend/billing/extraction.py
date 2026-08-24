"""Reads an invoice PDF with OpenAI and returns plain data.

**No ORM imports in this module, deliberately.** It takes bytes and returns a
dict, so it can be exercised from `manage.py shell` without touching the
database, and so swapping the engine later means rewriting one file and nothing
else. Resolving the extracted supplier to a `Customer` row is the *view's* job,
not this module's.

The PDF is sent to the model as a file, base64 inline rather than uploaded — the
project's decision is that the file is discarded after extraction, and inlining
means nothing is left sitting in OpenAI's file storage either. It also means a
scanned, image-only PDF is read by vision rather than failing outright, so no
OCR library is needed here or ever.

See docs/specs/2026-08-ocr-ingest.md.
"""

from __future__ import annotations

import base64
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import openai
from django.conf import settings

CENTS = Decimal("0.01")

# Reasons the frontend already knows how to render. Keep in sync with
# ExtractionFailure in frontend/src/types.ts.
NO_TEXT = "no_text"
TOO_LARGE = "too_large"
NOT_PDF = "not_pdf"
TIMEOUT = "timeout"


class ExtractionError(Exception):
    """A failure the user can act on, not a bug. Views turn these into 400s."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


# ---------------------------------------------------------------------------
# The contract with the model
# ---------------------------------------------------------------------------

PROMPT = """\
You are reading a single invoice. Extract what is printed on it. Do not calculate, \
infer, or tidy anything up — if a value is not on the page, return null rather than \
a guess.

Rules that matter:

- THE CUSTOMER IS THE PARTY THE INVOICE IS ADDRESSED TO — the one under "Bill to", \
"Invoice to", "Customer" or "Sold to". It is NOT the party issuing the invoice, \
whose name usually sits at the top as a letterhead. Take the name, the email and \
the postal address of that same addressed party, all three together: never mix one \
party's name with the other party's contact details. If the invoice shows no \
addressed party at all, return null for customer rather than falling back to the \
issuer.

- Money and quantities: return them exactly as printed, as strings, without \
currency symbols or thousands separators. "Rs 6,000.00" is "6000.00".
- Dates: ISO 8601, YYYY-MM-DD. A date written 20/07/2026 is ambiguous between \
day-first and month-first; pick the reading that makes the due date fall on or \
after the issue date, and flag it.
- One line item per row of the invoice's table. Do not merge rows, do not split \
one row into several, and do not include subtotal, tax or total rows as line items.
- printed_total is the grand total PRINTED ON THE PAGE. Do not compute it from the \
rows — it is used as a cross-check against them, so computing it would defeat the \
purpose. Null if no total is printed.
- source_invoice_number is the supplier's own invoice number as printed.
- low_confidence lists the field paths you are genuinely unsure about, using the \
paths "issue_date", "due_date", "notes", "source_invoice_number", "printed_total", \
or "transactions.<zero-based index>.<description|quantity|unit_price>". Flag \
anything ambiguous, struck through, handwritten, cut off or blurred. Be honest: an \
unflagged wrong value costs more than a flagged right one.
- notes_by_field explains each flagged path in one short sentence, in plain \
sentence case, e.g. 'Read as "20/07" — could be 20 July or 7 December.'
- If the document has no readable content at all, or is clearly not an invoice, \
return has_content: false and leave everything else empty.
"""

_MONEY_STRING = {"type": "string"}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    # Strict mode requires every property to be listed in `required`; optional
    # values are expressed by allowing null, not by omission.
    "required": [
        "has_content",
        "source_invoice_number",
        "issue_date",
        "due_date",
        "notes",
        "customer",
        "transactions",
        "printed_total",
        "low_confidence",
        "notes_by_field",
        "page_count",
    ],
    "properties": {
        "has_content": {"type": "boolean"},
        "source_invoice_number": {"type": ["string", "null"]},
        "issue_date": {"type": ["string", "null"]},
        "due_date": {"type": ["string", "null"]},
        "notes": {"type": "string"},
        # The party the invoice is addressed TO. Invoice.customer means the party
        # being billed, so pulling the issuer's letterhead here would file every
        # uploaded invoice against the wrong company — and, because extraction
        # creates customers, would create that wrong company as a row.
        "customer": {
            "type": ["object", "null"],
            "description": "The party the invoice is addressed to (bill to), never the issuer.",
            "additionalProperties": False,
            "required": ["name", "email", "billing_address"],
            "properties": {
                "name": {"type": "string", "description": "Name of the party being billed."},
                "email": {"type": "string", "description": "Email of the party being billed."},
                "billing_address": {
                    "type": "string",
                    "description": "Postal address of the party being billed.",
                },
            },
        },
        "transactions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["description", "quantity", "unit_price"],
                "properties": {
                    "description": {"type": "string"},
                    "quantity": _MONEY_STRING,
                    "unit_price": _MONEY_STRING,
                },
            },
        },
        "printed_total": {"type": ["string", "null"]},
        "low_confidence": {"type": "array", "items": {"type": "string"}},
        # Strict mode cannot express an object with arbitrary keys, so per-field
        # notes arrive as a list of pairs and are folded into a dict below.
        "notes_by_field": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "note"],
                "properties": {"path": {"type": "string"}, "note": {"type": "string"}},
            },
        },
        "page_count": {"type": "integer"},
    },
}


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_NOT_NUMERIC = re.compile(r"[^0-9.\-]")


def to_money(raw: object) -> str | None:
    """A 2dp string, or None when the value cannot be read as a number.

    The model is told to return bare numeric strings but is not trusted to: this
    strips currency symbols and thousands separators, then quantizes the same way
    `Transaction.line_total` does (ROUND_HALF_UP), so a value that survives here
    is already in the form the API contract requires. Callers treat None as
    "flag this field" rather than as zero — see `_money_or_flag`.
    """
    if raw is None:
        return None
    text = _NOT_NUMERIC.sub("", str(raw).strip())
    if not text or text in {"-", ".", "-."}:
        return None
    try:
        return str(Decimal(text).quantize(CENTS, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def to_date(raw: object) -> str | None:
    """Pass through an ISO date, drop anything else."""
    if not raw:
        return None
    text = str(raw).strip()
    return text if _ISO_DATE.match(text) else None


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------


def extract_invoice_fields(pdf_bytes: bytes, filename: str) -> dict:
    """Read an invoice PDF. Raises ExtractionError for anything the user can fix.

    Returns a dict with the keys the API contract documents, minus `customer`
    resolution: `customer_guess` here is what was printed on the page, and it is
    the caller's job to turn that into a real row.
    """
    if not pdf_bytes:
        raise ExtractionError(NOT_PDF, "The uploaded file is empty.")

    encoded = base64.b64encode(pdf_bytes).decode("ascii")
    client = openai.OpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=settings.OPENAI_TIMEOUT_SECONDS,
        max_retries=1,
    )

    try:
        response = client.responses.create(
            model=settings.OPENAI_MODEL,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "filename": filename,
                            "file_data": f"data:application/pdf;base64,{encoded}",
                        },
                        {"type": "input_text", "text": PROMPT},
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "invoice_extraction",
                    "strict": True,
                    "schema": SCHEMA,
                }
            },
        )
    except openai.APITimeoutError as exc:
        raise ExtractionError(
            TIMEOUT, "Reading the PDF took too long. Try again, or enter it by hand."
        ) from exc
    except openai.BadRequestError as exc:
        # Almost always a file the model cannot open at all.
        raise ExtractionError(
            NOT_PDF, f"{filename} could not be read as a PDF."
        ) from exc
    except openai.APIError as exc:
        # Auth, rate limit, outage. Not the user's fault and not actionable by
        # them, but a 400 with a plain message beats a 500 with a traceback.
        raise ExtractionError(
            TIMEOUT, "The extraction service is unavailable right now. Try again shortly."
        ) from exc

    try:
        payload = json.loads(response.output_text)
    except (AttributeError, ValueError) as exc:
        raise ExtractionError(
            NO_TEXT, f"Nothing readable came back for {filename}."
        ) from exc

    if not payload.get("has_content"):
        raise ExtractionError(
            NO_TEXT,
            f"No readable invoice content was found in {filename}. "
            "The pages may be images with no text layer, or this may not be an invoice.",
        )

    return _normalise(payload)


def _normalise(payload: dict) -> dict:
    """Coerce the model's output into the shape the API promises.

    Anything unparseable is not dropped and not silently zeroed — it is set to a
    safe value AND its path is added to `low_confidence`, so it arrives at the
    review screen already marked for a human to look at.
    """
    flags = {str(p) for p in payload.get("low_confidence") or []}
    notes = {
        str(item["path"]): str(item["note"])
        for item in payload.get("notes_by_field") or []
        if item.get("path") and item.get("note")
    }

    def money_or_flag(raw, path, fallback="0.00"):
        value = to_money(raw)
        if value is None:
            flags.add(path)
            notes.setdefault(path, "Could not be read as a number — check it against the PDF.")
            return fallback
        return value

    lines = []
    for index, row in enumerate(payload.get("transactions") or []):
        lines.append(
            {
                "description": str(row.get("description") or "").strip(),
                "quantity": money_or_flag(row.get("quantity"), f"transactions.{index}.quantity"),
                "unit_price": money_or_flag(
                    row.get("unit_price"), f"transactions.{index}.unit_price"
                ),
            }
        )

    for field in ("issue_date", "due_date"):
        if payload.get(field) and to_date(payload.get(field)) is None:
            flags.add(field)
            notes.setdefault(field, "Not a recognisable date — check it against the PDF.")

    guess = payload.get("customer") or None
    if guess:
        guess = {
            "name": str(guess.get("name") or "").strip(),
            "email": str(guess.get("email") or "").strip(),
            "billing_address": str(guess.get("billing_address") or "").strip(),
        }
        if not guess["name"]:
            guess = None

    # printed_total stays None when unreadable rather than becoming 0.00: it is a
    # cross-check, and a fake zero would report a disagreement that isn't real.
    printed_total = to_money(payload.get("printed_total"))

    return {
        "source_invoice_number": (payload.get("source_invoice_number") or None),
        "issue_date": to_date(payload.get("issue_date")),
        "due_date": to_date(payload.get("due_date")),
        "notes": str(payload.get("notes") or "").strip(),
        "customer_guess": guess,
        "transactions": lines,
        "printed_total": printed_total,
        # Only keep notes for paths that are actually flagged, so the UI never
        # shows an explanation next to a field with no marker on it.
        "low_confidence": sorted(flags),
        "field_notes": {path: note for path, note in notes.items() if path in flags},
        "page_count": int(payload.get("page_count") or 0),
    }
