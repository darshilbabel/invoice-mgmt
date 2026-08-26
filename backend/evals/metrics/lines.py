"""The line items: did the extractor read the invoice's table, row for row.

Reads the alignment computed once in `dataset.py` — see `evals/align.py` for why
matching is a two-stage deterministic pass and not index order or a judge.

Three separate metrics rather than one, because the failures they catch call for
different responses and averaging them together hides all three:

- `LineItemFidelity` — did every row on the page come back, and only those rows.
- `LineItemNumerics` — of the rows that came back, were the numbers right. **This is
  the money bug.** A row matched by description with the wrong unit price produces a
  wrong invoice total, silently, because `Invoice.total` is computed and there is no
  stored figure to contradict it.
- `NoSummaryRows` — did a subtotal, tax or total row get imported as a line item.

`NoSummaryRows` deserves its own metric rather than being folded into fidelity's
"spurious row" count. The prompt forbids it specifically (*"do not include subtotal,
tax or total rows as line items"*), and it is the one spurious row that inflates the
invoice by roughly double rather than by one line — a `Grand total` row added to the
lines it summarises. Counting it as a generic extra row would put a catastrophic
error and a duplicated hosting line in the same bucket.
"""

from __future__ import annotations

import re

from evals.align import normalise_description
from evals.metrics.base import DeterministicMetric, Result, ratio

#: Words that mean a row is a summary of other rows, not a line item itself. Used
#: only as a fallback: a fixture's own `forbidden_descriptions`, read off the page,
#: is always better evidence. This catches the invoice nobody thought to annotate.
SUMMARY_WORDS = re.compile(
    r"\b(sub ?total|total|amount due|balance due|tax|gst|vat|cgst|sgst|igst|"
    r"discount|shipping|freight|round ?off)\b"
)


class LineItemFidelity(DeterministicMetric):
    """Every row on the page, and no rows that were not."""

    name = "Line items - fidelity"

    def evaluate(self, case) -> Result:
        alignment = case.alignment
        golden_rows = len(case.golden.line_items)
        extracted_rows = len(case.outcome.transactions)
        matched = len(alignment.pairs)

        recall = ratio(matched, golden_rows)
        precision = ratio(matched, extracted_rows)
        # Harmonic mean: one row missed and one row invented should not average out
        # to "fine". F1 punishes the pair, which is the honest reading.
        score = (
            0.0
            if (precision + recall) == 0
            else 2 * precision * recall / (precision + recall)
        )

        parts = [
            f"{matched}/{golden_rows} rows found, {extracted_rows} returned "
            f"(recall {recall:.0%}, precision {precision:.0%})"
        ]
        if alignment.missed:
            parts.append(
                "missed: "
                + "; ".join(
                    repr(case.golden.line_items[i].description)
                    for i in alignment.missed
                )
            )
        if alignment.spurious:
            parts.append(
                "not on the page: "
                + "; ".join(
                    repr(case.outcome.transactions[i].get("description"))
                    for i in alignment.spurious
                )
            )
        if not alignment.order_preserved:
            # Not scored: row order is not part of the API contract. Surfaced
            # because reordering is the observable proxy for the merge and split
            # failures the prompt forbids, and it is worth a human's glance.
            parts.append("rows came back in a different order than they appear")

        return Result(score=score, reason=". ".join(parts), detail=alignment.summary())


class LineItemNumerics(DeterministicMetric):
    """Of the rows that were found, how many have exactly the right money.

    Scored over matched pairs only, on purpose. A row that was never found is
    `LineItemFidelity`'s failure; counting it here too would report one fault twice
    and make it impossible to tell a missed row from a misread one.
    """

    name = "Line items - numerics"

    def evaluate(self, case) -> Result:
        alignment = case.alignment
        matched = len(alignment.pairs)
        exact = len(alignment.exact)
        score = ratio(exact, matched)

        if not matched:
            return Result(
                score=score,
                reason="no rows matched, so there are no numbers to check — see "
                "line-item fidelity",
                detail=alignment.summary(),
            )

        if not alignment.numeric_errors:
            return Result(
                score=score,
                reason=f"all {exact} matched rows have exactly the right quantity "
                "and unit price",
                detail=alignment.summary(),
            )

        misreads = [
            f"{pair.golden.get('description')!r}: read "
            f"{pair.extracted.get('quantity')} x {pair.extracted.get('unit_price')}, "
            f"printed {pair.golden.get('quantity')} x {pair.golden.get('unit_price')}"
            for pair in alignment.numeric_errors
        ]
        return Result(
            score=score,
            reason=(
                f"{len(alignment.numeric_errors)} of {matched} matched rows have "
                "wrong money, which makes the computed invoice total wrong: "
                + "; ".join(misreads)
            ),
            detail=alignment.summary(),
        )


class NoSummaryRows(DeterministicMetric):
    """A subtotal, tax or total row must never come back as a line item."""

    name = "No summary rows"

    def evaluate(self, case) -> Result:
        forbidden = {
            normalise_description(text)
            for text in case.golden.forbidden_descriptions
            if str(text).strip()
        }

        offenders: list[str] = []
        for row in case.outcome.transactions:
            description = row.get("description")
            normalised = normalise_description(description)
            if not normalised:
                continue
            declared = normalised in forbidden
            heuristic = bool(SUMMARY_WORDS.search(normalised))
            if declared or heuristic:
                why = "listed in the fixture" if declared else "reads as a summary row"
                offenders.append(f"{description!r} ({why})")

        if not offenders:
            return Result(
                score=1.0,
                reason="no subtotal, tax or total row was imported as a line item",
            )

        return Result(
            score=0.0,
            reason=(
                f"{len(offenders)} summary row(s) imported as line items, which "
                "double-counts them into the invoice total: " + "; ".join(offenders)
            ),
            detail={"offenders": offenders},
        )
