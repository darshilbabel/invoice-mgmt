"""The rule `docs/domain.md` calls the single load-bearing rule of the system.

    Invoice totals are computed from the invoice's transactions, never stored.

Extraction is upstream of that. The line items it returns become `Transaction` rows,
and `Invoice.total` is derived from them — so if the lines are wrong, the invoice is
wrong and nothing in the system disagrees, because there is no stored total to
disagree with. `printed_total` exists as the one independent witness: the number the
supplier put on the page.

This metric checks three numbers against each other:

  A. the total implied by the **golden** line items   (what the page really says)
  B. the total implied by the **extracted** line items (what would get saved)
  C. `printed_total` as extracted                      (the page's own witness)

A vs B is the one that matters — it is the invoice the user would end up with. B vs C
is the app's own cross-check, the one the review screen shows as an agreement line;
when those disagree, the extractor produced a self-inconsistent result and the user
is told so. Both are worth scoring, and they fail for different reasons.

## The rounding order, and why it is checked rather than assumed

`docs/domain.md` is emphatic that rounding each line before summing is not the same
as summing then rounding:

> three lines of `0.25 x 0.50` are `0.39` per-line but `0.38` sum-first. That is a
> real cent of drift between the dashboard and the invoice list.

So this module computes **both** and asserts the per-line-rounded figure is the one
that reconciles. Computing only the correct one would leave the suite unable to tell
you whether it is following the rule or merely agreeing with itself — and on most
invoices the two are equal, so the mistake would be invisible until the one invoice
where it is not.

That also makes the check vacuous unless some fixture actually exercises the
divergence, which is why `scaffold.py` records `rounding_divergent` and
`dataset.py` warns when no loaded fixture has it set.
"""

from __future__ import annotations

from evals.metrics.base import DeterministicMetric, Result
from evals.money import money_str, round_then_sum, sum_then_round


class TotalReconciliation(DeterministicMetric):
    """Do the extracted line items add up to the invoice on the page."""

    name = "Total reconciliation"

    def evaluate(self, case) -> Result:
        golden_lines = [item.model_dump() for item in case.golden.line_items]
        extracted_lines = case.outcome.transactions

        from_golden = round_then_sum(golden_lines)
        from_extracted = round_then_sum(extracted_lines)
        printed = case.payload.get("printed_total")

        scores: list[float] = []
        parts: list[str] = []

        # --- A vs B: the invoice the user would actually save ----------------
        lines_agree = from_golden == from_extracted
        scores.append(1.0 if lines_agree else 0.0)
        if lines_agree:
            parts.append(f"line items total {money_str(from_extracted)}, matching the page")
        else:
            drift = from_extracted - from_golden
            parts.append(
                f"line items total {money_str(from_extracted)} but the page comes to "
                f"{money_str(from_golden)} — the saved invoice would be off by "
                f"{money_str(abs(drift))}"
            )

        # --- B vs C: the app's own cross-check --------------------------------
        if printed is None:
            if not case.golden.printed_total_absent:
                # A total was printed and the extractor did not return it. Scored,
                # because the review screen loses its agreement line entirely.
                scores.append(0.0)
                parts.append(
                    "no printed_total came back, so the review screen has nothing "
                    "to cross-check the rows against"
                )
            else:
                parts.append("no total printed on the page, correctly reported as none")
        else:
            self_consistent = money_str(from_extracted) == str(printed)
            scores.append(1.0 if self_consistent else 0.0)
            if not self_consistent:
                parts.append(
                    f"extracted rows sum to {money_str(from_extracted)} but the "
                    f"extracted printed_total is {printed} — a row was misread"
                )

        # --- the rounding order itself ---------------------------------------
        rounded_first = round_then_sum(extracted_lines)
        summed_first = sum_then_round(extracted_lines)
        if rounded_first != summed_first:
            # This invoice is one of the ones that can tell the two rules apart.
            # Whether the *correct* rule is the one that reconciles is the check.
            correct_reconciles = rounded_first == from_golden
            scores.append(1.0 if correct_reconciles else 0.0)
            parts.append(
                "this invoice distinguishes the rounding orders "
                f"(per-line {money_str(rounded_first)} vs sum-first "
                f"{money_str(summed_first)}); "
                + (
                    "the per-line rule reconciles, as docs/domain.md requires"
                    if correct_reconciles
                    else "the per-line rule does NOT reconcile — check the lines"
                )
            )

        return Result(
            score=sum(scores) / len(scores) if scores else 1.0,
            reason=". ".join(parts),
            detail={
                "from_golden_lines": money_str(from_golden),
                "from_extracted_lines": money_str(from_extracted),
                "printed_total": printed,
                "sum_then_round": money_str(summed_first),
                "rounding_divergent": rounded_first != summed_first,
            },
        )
