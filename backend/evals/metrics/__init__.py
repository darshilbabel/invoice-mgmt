"""The metric set, and the one rule that divides it.

**Numbers and dates are never scored by a model.** Money, quantities, dates, counts
and set membership are compared exactly, by the `DeterministicMetric` subclasses in
this package. The judge in `judged.py` gets three questions and only three, all of
them about whether two strings name the same thing.

`deterministic_metrics()` needs no API key and costs nothing, which is why it is
usable on its own — see `evals/README.md` for running the free layers alone.
"""

from evals.metrics.base import DeterministicMetric, Result
from evals.metrics.calibration import ConfidenceCalibration
from evals.metrics.contract import LowConfidencePathsResolve
from evals.metrics.direction import PartyDirection
from evals.metrics.lines import LineItemFidelity, LineItemNumerics, NoSummaryRows
from evals.metrics.rejection import (
    NothingFabricated,
    RefusalRate,
    RejectionOutcome,
    rejection_metrics,
)
from evals.metrics.scalars import ScalarFields
from evals.metrics.totals import TotalReconciliation

__all__ = [
    "ConfidenceCalibration",
    "DeterministicMetric",
    "LineItemFidelity",
    "LineItemNumerics",
    "LowConfidencePathsResolve",
    "NoSummaryRows",
    "NothingFabricated",
    "PartyDirection",
    "RefusalRate",
    "RejectionOutcome",
    "Result",
    "ScalarFields",
    "TotalReconciliation",
    "deterministic_metrics",
    "rejection_metrics",
]


def deterministic_metrics() -> list[DeterministicMetric]:
    """Every metric for a fixture that produced a payload. Worst consequence first.

    A fixture whose golden declares `expect_error` takes `rejection_metrics()`
    instead — scoring an empty payload with these would report "all four scalar
    fields missed", which describes a failure where refusing was the right answer.
    """
    return [
        # Writes a permanent Customer row for the wrong company. Threshold 1.0.
        PartyDirection(),
        # Wrong money on a row -> wrong invoice total, with nothing to contradict it.
        LineItemNumerics(threshold=1.0),
        # A summary row imported as a line item roughly doubles the invoice.
        NoSummaryRows(threshold=1.0),
        # The three-way check against what the supplier printed.
        TotalReconciliation(threshold=1.0),
        # Rows missed or invented.
        LineItemFidelity(threshold=0.9),
        # Fabricated dates score worst here; plain misses get partial credit.
        ScalarFields(threshold=0.9),
        # Confidently wrong is the failure the amber review UI exists to prevent.
        ConfidenceCalibration(threshold=0.8),
        # A flagged path that names nothing breaks the review screen's counter.
        LowConfidencePathsResolve(threshold=1.0),
    ]
