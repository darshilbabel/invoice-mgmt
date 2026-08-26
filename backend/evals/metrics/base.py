"""Shared plumbing for the deterministic metrics.

Everything in this package that is *not* `judged.py` subclasses `DeterministicMetric`.
That split is the suite's central rule, so it is worth stating plainly here:

**Numbers and dates are never scored by a model.** A judge that decides "6,000 and
6000.00 are basically the same" is exactly the bug this suite exists to catch. Money,
quantities, dates, counts and set membership are compared with `==` on strings that
have already been normalised to one form. The judge in `judged.py` is confined to the
three questions where a string can be correct in more than one shape.

Subclasses implement `evaluate(case) -> Result`. The base handles deepeval's
interface: `measure` / `a_measure` / `is_successful`, the `score` / `success` /
`reason` attributes, and turning an unexpected exception into a failed metric with a
legible reason rather than a stack trace in the middle of a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

if TYPE_CHECKING:  # pragma: no cover
    from evals.dataset import Case


@dataclass
class Result:
    """A metric's verdict: a score, and a sentence saying why."""

    score: float
    reason: str
    #: Extra detail for a human debugging a failure. Not scored.
    detail: dict = field(default_factory=dict)


def ratio(numerator: int, denominator: int, *, empty: float = 1.0) -> float:
    """`numerator / denominator`, with an explicit answer for an empty denominator.

    `empty` defaults to 1.0 — "nothing to get wrong here" scores as passing, not as
    failing. A metric where that is the wrong reading says so at the call site.
    """
    return empty if denominator == 0 else numerator / denominator


class DeterministicMetric(BaseMetric):
    """A metric computed from the payload and the golden. No model, no network."""

    #: Shown in deepeval's report.
    name: str = "Deterministic"

    def __init__(self, threshold: float = 1.0):
        # Provisional by default. Real thresholds come from a baseline over real
        # invoices — a number invented before seeing one is either always green or
        # always red. See evals/README.md.
        self.threshold = threshold
        self.score: float | None = None
        self.success: bool | None = None
        self.reason: str | None = None
        self.error: str | None = None
        # Never a judge, so nothing to charge and nothing to report.
        self.evaluation_cost = 0.0

    # --- subclasses implement this ----------------------------------------

    def evaluate(self, case: "Case") -> Result:
        raise NotImplementedError

    # --- deepeval's interface ---------------------------------------------

    def _case(self, test_case: LLMTestCase) -> "Case":
        metadata = test_case.metadata or {}
        case = metadata.get("case")
        if case is None:
            raise ValueError(
                "This test case carries no fixture in metadata['case']. Metrics in "
                "this suite read structured data from there — build test cases with "
                "evals.dataset.load_test_cases(), not by hand."
            )
        return case

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        try:
            result = self.evaluate(self._case(test_case))
            self.score = result.score
            self.reason = result.reason
            self.error = None
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            # A metric that raises mid-run would abort the whole suite, discarding
            # every other metric's verdict on a billable run. Failing this one
            # metric with the exception as its reason keeps the rest of the report.
            self.score = 0.0
            self.reason = f"{type(exc).__name__}: {exc}"
            self.error = str(exc)
        self.success = self.is_successful()
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        # Nothing here does I/O, so there is no async version worth having.
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        if self.error is not None:
            self.success = False
        elif self.score is None:
            self.success = False
        else:
            self.success = self.score >= self.threshold
        return self.success

    @property
    def __name__(self):  # noqa: A003 - deepeval reads this for the report
        return self.name
