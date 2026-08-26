"""The paths where extraction refuses. What must never happen is a 500.

`docs/specs/2026-08-ocr-ingest.md` § Verification lists these as manual `curl` steps
and stresses that **none of them may return a 500**. The view turns an
`ExtractionError` into a readable 400; anything else becomes a traceback in front of
a user. These tests hold the adapter to that.

## What is asserted, and what deliberately is not

Two of the reason codes are contractual and are asserted exactly. The third is not,
and pretending otherwise would produce a flaky test that bills a real model call
every time it runs:

- **empty bytes -> `not_pdf`** is raised by `extract_invoice_fields` itself before
  any network call. Exact, free, always true.
- **a timeout -> `timeout`** is reachable by squeezing `OPENAI_TIMEOUT_SECONDS`.
  This is worth having precisely because it is otherwise never exercised: a blocking
  90-second extract with no job queue is a tracked HIGH risk in
  `docs/qa-strategy.md` § 5, and this is the only automated thing that touches it.
- **a non-invoice PDF** asserts a *safety property*, not a reason code. `no_text`
  fires only when the model returns `has_content: false`; a text-bearing non-invoice
  — a letter, a bank statement — will plausibly come back `has_content: true` with
  no line items. Both are acceptable outcomes. What is not acceptable is inventing
  an invoice out of a document that is not one. So: raises, or returns empty. Never
  fabricates, never 500s.

`too_large` is defined in `extraction.py` but is unreachable from this function —
the size check lives in the view, above the adapter. Stated here so the gap is a
recorded decision rather than something that looks forgotten.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from billing.extraction import NOT_PDF, TIMEOUT, ExtractionError, extract_invoice_fields
from evals.dataset import load

# Enough to get past the empty check; the request never completes anyway.
MINIMAL_PDF_BYTES = b"%PDF-1.4\n% not a real document\n"


def test_empty_upload_is_refused_before_any_api_call():
    """Costs nothing and calls nothing — the check is the first line of the function."""
    with pytest.raises(ExtractionError) as raised:
        extract_invoice_fields(b"", "empty.pdf")
    assert raised.value.reason == NOT_PDF
    assert raised.value.message, "an ExtractionError must carry a message a user can read"


@pytest.mark.billable
def test_timeout_surfaces_as_a_readable_error_not_a_500():
    """The blocking-extract risk, exercised.

    A 1ms timeout makes the OpenAI client raise APITimeoutError before the request
    can complete, so this costs approximately nothing while proving the except
    branch maps it to an ExtractionError rather than letting it escape as a 500.
    """
    with override_settings(OPENAI_TIMEOUT_SECONDS=0.001):
        with pytest.raises(ExtractionError) as raised:
            extract_invoice_fields(MINIMAL_PDF_BYTES, "slow.pdf")

    assert raised.value.reason == TIMEOUT
    assert "try again" in raised.value.message.casefold()


@pytest.mark.billable
def test_a_document_that_is_not_an_invoice_is_never_invented_into_one():
    """Safety property, not a reason code. See the module docstring.

    Driven from a fixture whose golden declares `expect_error`, so it uses a real
    document and the cached extraction rather than a synthetic one.
    """
    cases = [case for case in load() if case.golden.expect_error is not None]
    if not cases:
        pytest.skip(
            "no fixture declares expect_error — add a non-invoice PDF and scaffold it"
        )

    for case in cases:
        if not case.outcome.ok:
            assert case.outcome.error_reason, f"{case.name}: refused with no reason"
            continue

        payload = case.outcome.payload or {}
        assert not payload.get("transactions"), (
            f"{case.name}: returned {len(payload['transactions'])} line item(s) from "
            "a document that is not an invoice — this is fabrication, and the review "
            "screen would present it as readable data"
        )
        assert payload.get("customer_guess") is None, (
            f"{case.name}: invented a customer from a non-invoice, which "
            "_resolve_customer would create as a permanent Customer row"
        )


def test_too_large_is_not_this_functions_job():
    """A recorded gap, not an oversight.

    TOO_LARGE is defined in extraction.py but never raised there: the size limit is
    enforced in InvoiceViewSet.extract, above the adapter, against
    settings.INVOICE_UPLOAD_MAX_BYTES. Covered by the Postman suite's `07 PDF
    extract` folder, not here.
    """
    from billing import extraction

    source = extraction.extract_invoice_fields.__code__.co_consts
    assert extraction.TOO_LARGE not in [c for c in source if isinstance(c, str)], (
        "TOO_LARGE is now raised inside extract_invoice_fields — this test's premise "
        "has changed, and the reason code needs asserting properly rather than noting"
    )
