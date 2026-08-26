"""Metrics for a fixture whose correct outcome is a refusal rather than a payload.

Every other metric in this package scores what came back. These score the fact that
nothing did, which needs its own module because the payload metrics cannot express
it: `ScalarFields` over an empty payload scores "all four fields missed", which is
a description of a *failure*, and here it is the correct answer.

## Why a refusal is worth scoring at all

`billing/extraction.py` refuses in two places, and the difference matters:

- **Before the model is called** — an empty upload, or a file the API cannot open.
- **After the model is called** — the model read the page and set `has_content:
  false`, meaning it looked and found no invoice.

Both raise `ExtractionError`, both reach the user as the same 400, and both produce
no payload. `metrics/trace.py` is what tells them apart, and this module is the
other half: the reason code the golden declares has to be the one that came back,
because `no_text` and `not_pdf` send the user to two different remedies.

## The safety property

`NothingFabricated` is here rather than in `test_failure_modes.py` because it is a
score, not a boolean: a document too degraded to read is the single most likely
input to produce an invented invoice, and inventing one is the worst thing this
system can do with it. A returned line item is a number a human will approve on the
review screen. An invented customer is a permanent `Customer` row — `on_delete=
PROTECT`, so it cannot even be cleaned up once an invoice references it.

It scores a case that returned a payload at all, which is why it is not simply the
inverse of `RejectionOutcome`. A fixture that should have refused and instead
returned something empty-but-well-formed is a different, milder failure than one
that returned three confident line items, and the two should not score the same.
"""

from __future__ import annotations

from evals.metrics.base import DeterministicMetric, Result


class RejectionOutcome(DeterministicMetric):
    """Did it refuse, and with the reason code the golden declares."""

    name = "Refused, with the right reason"

    def evaluate(self, case) -> Result:
        expected = case.golden.expect_error
        if expected is None:
            raise ValueError(
                f"{case.name} has no expect_error, so this metric does not apply to "
                "it. Rejection metrics are selected per fixture — see evals/report.py."
            )

        outcome = case.outcome

        if outcome.ok:
            return Result(
                score=0.0,
                reason=(
                    f"EXTRACTED a payload from a document whose correct outcome is a "
                    f"refusal ({expected.reason}). Whatever is in that payload was "
                    "not read off the page — see the fabrication metric for what it "
                    "contains."
                ),
                detail={"expected_reason": expected.reason, "actual_reason": None},
            )

        if outcome.error_reason != expected.reason:
            return Result(
                score=0.0,
                reason=(
                    f"refused with {outcome.error_reason!r}, but the golden declares "
                    f"{expected.reason!r}. Both are refusals, so nothing wrong is "
                    "saved either way — but the reason code is what the upload "
                    "screen renders, and these two send the user to different "
                    "remedies."
                ),
                detail={
                    "expected_reason": expected.reason,
                    "actual_reason": outcome.error_reason,
                },
            )

        return Result(
            score=1.0,
            reason=f"refused with {outcome.error_reason!r}, as the golden declares",
            detail={
                "expected_reason": expected.reason,
                "actual_reason": outcome.error_reason,
                "message": outcome.error_message,
            },
        )


class NothingFabricated(DeterministicMetric):
    """If anything did come back, it invented neither a line item nor a customer."""

    name = "Nothing fabricated"

    def evaluate(self, case) -> Result:
        if not case.outcome.ok:
            return Result(
                score=1.0,
                reason="nothing came back at all, so nothing could be invented",
                detail={"payload": None},
            )

        payload = case.payload
        rows = payload.get("transactions") or []
        customer = payload.get("customer_guess")

        problems = []
        if rows:
            problems.append(
                f"{len(rows)} line item(s) — money a reviewer would be shown as "
                "readable data"
            )
        if customer:
            problems.append(
                f"a customer ({customer.get('name')!r}) — _resolve_customer would "
                "create this as a permanent Customer row, and Customer is PROTECT"
            )

        if problems:
            return Result(
                score=0.0,
                reason="INVENTED " + "; and ".join(problems),
                detail={"rows": len(rows), "customer": customer},
            )

        return Result(
            score=1.0,
            reason=(
                "a payload came back where a refusal was expected, but it carries no "
                "line items and no customer — wrong outcome, nothing fabricated"
            ),
            detail={"rows": 0, "customer": None},
        )


class RefusalRate(DeterministicMetric):
    """Does it refuse this page *every* time, or only sometimes.

    The metric the other two in this module cannot be trusted without. They score
    the one cached extraction; this one scores the distribution behind it. On a page
    at the edge of readability those are different questions, and only this one has
    a consequence: a fixture that refuses on nine runs in ten still ships a
    fabricated invoice on the tenth.

    Threshold is 1.0 and is not provisional. There is no acceptable rate at which a
    system invents an invoice from a page nobody can read — the fabrications carry
    invented customers (a permanent `Customer` row, `on_delete=PROTECT`) and invented
    totals (a number a reviewer approves believing it was read off the page).

    Scores the refusal rate directly, so the number is the thing you act on: 0.62
    means it fabricated on nearly four runs in ten.
    """

    name = "Refuses every time"

    def __init__(self, samples, threshold: float = 1.0):
        super().__init__(threshold=threshold)
        self.samples = samples

    def evaluate(self, case) -> Result:
        stats = self.samples
        if not stats.count:
            return Result(
                score=0.0,
                reason="no samples collected — run with --extract-samples N",
                detail={},
            )

        rate = stats.refusal_rate
        if stats.refusals == stats.count:
            return Result(
                score=1.0,
                reason=f"refused all {stats.count} times",
                detail={"samples": stats.count, "refusals": stats.refusals},
            )

        customers = stats.fabricated_customers()
        totals = stats.fabricated_totals()
        unflagged = stats.unflagged_fabrications()

        parts = [
            f"FABRICATED an invoice on {stats.count - stats.refusals} of "
            f"{stats.count} runs of the same page"
        ]
        if customers:
            parts.append(
                "invented customers: "
                + ", ".join(repr(name) for name in customers)
                + " — _resolve_customer creates each as a permanent Customer row"
            )
        if totals:
            parts.append("invented totals: " + ", ".join(totals))
        if unflagged:
            parts.append(
                f"{len(unflagged)} of those carried no low_confidence flag on the "
                "total, so the review screen would show them as read off the page"
            )

        return Result(
            score=rate,
            reason=". ".join(parts),
            detail={
                "samples": stats.count,
                "refusals": stats.refusals,
                "refusal_rate": rate,
                "fabrications": [s.fingerprint for s in stats.extractions],
            },
        )


def rejection_metrics(samples=None) -> list[DeterministicMetric]:
    """Every metric that applies to a fixture expecting a refusal. Worst first.

    `samples` is an `evals.stability.Samples`. Without one, `RefusalRate` is left
    out rather than passed an empty set — a metric that reports "no samples" as a
    failure would be indistinguishable from the failure it exists to catch.
    """
    metrics = [
        # Inventing an invoice from an unreadable page is the worst outcome here.
        NothingFabricated(threshold=1.0),
        # Refusing, and telling the user the thing that sends them to the right fix.
        RejectionOutcome(threshold=1.0),
    ]
    if samples is not None:
        # First: it is the only one that sees past the single cached extraction.
        metrics.insert(0, RefusalRate(samples, threshold=1.0))
    return metrics
