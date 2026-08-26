"""The single-value fields: dates, invoice number, printed total, page count.

Scored **three ways**, not two, and the third one is the reason this module exists
rather than being four lines of `==`.

`extraction.py`'s PROMPT is explicit: *"if a value is not on the page, return null
rather than a guess."* Under a plain correct/incorrect comparison, two very different
failures score identically:

- the model **missed** a due date that was printed — the user sees a blank field and
  fills it in, which is what the review screen is for;
- the model **invented** a due date that was not printed (issue date plus thirty
  days is the classic) — the user sees a confident, plausible, wrong value, and the
  review screen gives them no reason to doubt it.

The second one is how a wrong invoice gets saved. So a fabrication where the golden
says null scores 0 for that field and is named in the reason; a plain miss scores
partial credit. Weighting them the same would tell you the model got "one field
wrong" in both cases and leave you to find out which.

`page_count` is in here for a structural reason rather than a money one: it is the
only signal in the payload that says whether the model read the whole document. A
three-page invoice reported as one page predicts truncated line items before you
look at anything else.
"""

from __future__ import annotations

from evals.metrics.base import DeterministicMetric, Result

#: Fields compared straight across, extraction key -> golden attribute.
SCALAR_FIELDS = (
    ("issue_date", "issue_date"),
    ("due_date", "due_date"),
    ("source_invoice_number", "source_invoice_number"),
    ("printed_total", "printed_total"),
)

#: Partial credit for omitting a value that was on the page. Not zero, because a
#: blank field is visible to the reviewer and recoverable; not full, because it is
#: still work the extractor was supposed to do.
MISS_CREDIT = 0.5


def _normalise(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class ScalarFields(DeterministicMetric):
    """Correct / wrong / fabricated, across the invoice's single-value fields."""

    name = "Scalar fields"

    def evaluate(self, case) -> Result:
        golden = case.golden
        payload = case.payload

        scores: list[float] = []
        correct: list[str] = []
        wrong: list[str] = []
        missed: list[str] = []
        fabricated: list[str] = []

        for key, attribute in SCALAR_FIELDS:
            expected = _normalise(getattr(golden, attribute))
            actual = _normalise(payload.get(key))

            # printed_total is the one field whose null has two meanings, and the
            # golden says which: not printed on the page (null is correct) versus
            # printed but unreadable (null is a failure that should also have been
            # flagged). Without printed_total_absent this field is untestable.
            if key == "printed_total" and expected is None and not golden.printed_total_absent:
                # The golden does not record a total and does not claim the page
                # lacked one. Nothing can be concluded, so it is not scored.
                continue

            if expected == actual:
                scores.append(1.0)
                correct.append(key)
            elif expected is None:
                # Nothing was printed, but something came back.
                scores.append(0.0)
                fabricated.append(f"{key}={actual!r}")
            elif actual is None:
                scores.append(MISS_CREDIT)
                missed.append(f"{key} (expected {expected!r})")
            else:
                scores.append(0.0)
                wrong.append(f"{key}={actual!r}, expected {expected!r}")

        # page_count: structural, so scored but described separately.
        expected_pages = golden.page_count
        actual_pages = int(payload.get("page_count") or 0)
        pages_ok = expected_pages == actual_pages
        if expected_pages:
            scores.append(1.0 if pages_ok else 0.0)

        score = sum(scores) / len(scores) if scores else 1.0

        parts: list[str] = []
        if fabricated:
            parts.append(
                "FABRICATED (not on the page): " + "; ".join(fabricated)
            )
        if wrong:
            parts.append("wrong: " + "; ".join(wrong))
        if missed:
            parts.append("missed: " + "; ".join(missed))
        if expected_pages and not pages_ok:
            parts.append(
                f"page_count {actual_pages} but the document has {expected_pages} "
                "— expect truncated line items"
            )
        if not parts:
            parts.append(f"all {len(correct)} scalar fields correct")

        return Result(
            score=score,
            reason=". ".join(parts),
            detail={
                "correct": correct,
                "wrong": wrong,
                "missed": missed,
                "fabricated": fabricated,
                "page_count": {"expected": expected_pages, "actual": actual_pages},
            },
        )
