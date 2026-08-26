"""Turns fixture files into deepeval test cases, refusing the ones that would lie.

A fixture is a PDF and a `<name>.expected.json` beside it. This module pairs them,
validates the golden, runs the extractor through `runner.py` (cached), computes the
line alignment once, and hands back `LLMTestCase`s.

## Where the data goes, and why

`LLMTestCase` in deepeval 4.2 is a pydantic model with `extra="ignore"` — attributes
set on it are silently dropped, so structured data cannot simply be attached. The
declared carrier is `metadata`, and that is what the deterministic metrics read:
the whole extraction, the whole golden, and the alignment. `actual_output` and
`expected_output` get JSON dumps of the two payloads, which is what GEval renders
into its prompts and what shows up in a report.

The alignment is computed **here, once**, rather than inside each metric. Two metrics
independently guessing how extracted rows line up with golden rows will eventually
disagree, and that disagreement is indistinguishable from a bug in the extractor.

## The three refusals

Loading fails, loudly and by filename, when:

1. **`_verified` is still false.** The golden is a scaffold draft nobody has checked
   against the page. It would score close to 1.0 by construction and measure nothing.
2. **`issuer.name` is still null.** `scaffold.py` will not fill this in, deliberately
   — see its docstring. Without it, `metrics/direction.py` has nothing to compare
   against and the highest-consequence failure in the system goes unmeasured.
3. **The PDF named by `source_pdf` is missing.** Fixture PDFs are gitignored by
   default (real invoices carry names, addresses and amounts), so a fresh clone has
   goldens with no documents. Saying so plainly beats a confusing empty run.

A refusal is an error, not a skip. A fixture that silently drops out of a suite is
worse than no fixture: the run still reports green, over less than it claims.

## The coverage warning

`docs/domain.md`'s most-cited rule is that rounding each line before summing gives a
different answer from summing then rounding. `metrics/totals.py` checks it — but the
check is vacuous unless some fixture actually exercises the divergence. So the
scaffold records `rounding_divergent` per fixture and this module warns when no
loaded fixture has it set. A warning rather than an error: it is a gap in the golden
set, not a fault in the code, and it can only be closed by finding the right invoice.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path

from deepeval.test_case import LLMTestCase

from evals.align import Alignment, align
from evals.runner import Outcome, run_extraction
from evals.schema import Expected, parse_expected

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

GOLDEN_SUFFIX = ".expected.json"


class FixtureError(Exception):
    """A fixture that cannot be trusted. Always names the file."""


@dataclass
class Case:
    """One fixture, resolved: the golden, what the extractor said, and the alignment."""

    name: str
    pdf_path: Path
    golden_path: Path
    golden: Expected
    outcome: Outcome
    alignment: Alignment

    @property
    def payload(self) -> dict:
        return self.outcome.payload or {}

    def to_test_case(self) -> LLMTestCase:
        return LLMTestCase(
            name=self.name,
            # There is no natural "input" string for a PDF; the filename is what
            # identifies the case to a human reading the report.
            input=f"Extract the invoice printed in {self.pdf_path.name}",
            actual_output=json.dumps(self.payload, indent=2, sort_keys=True),
            expected_output=json.dumps(
                self.golden.model_dump(by_alias=True), indent=2, sort_keys=True, default=str
            ),
            metadata={
                "case": self,
                "extracted": self.payload,
                "golden": self.golden,
                "alignment": self.alignment,
                "outcome": self.outcome,
            },
        )


def _read_golden(golden_path: Path) -> Expected:
    try:
        raw = json.loads(golden_path.read_text())
    except ValueError as exc:
        raise FixtureError(f"{golden_path.name} is not valid JSON: {exc}") from exc

    try:
        golden = parse_expected(raw)
    except ValueError as exc:
        raise FixtureError(f"{golden_path.name} is not a valid golden:\n{exc}") from exc

    if not golden.verified:
        raise FixtureError(
            f'{golden_path.name} still has "_verified": false.\n'
            "It is a scaffold draft — the values in it came from the extractor, "
            "which is the thing being measured. Read the PDF, correct every field, "
            "then set _verified to true. Until then this fixture would score close "
            "to 1.0 by construction and tell you nothing."
        )

    if not (golden.issuer.name or "").strip():
        raise FixtureError(
            f"{golden_path.name} has no issuer.name.\n"
            "scaffold.py leaves it blank on purpose: it is the one field that "
            "proves the extractor picked the right party, so the extractor is not "
            "allowed to supply it. Read the letterhead off the PDF and fill it in. "
            "Without it, metrics/direction.py cannot check the failure that creates "
            "permanent Customer rows from the wrong company."
        )

    return golden


def load(fixtures_dir: Path | None = None, refresh: bool | None = None) -> list[Case]:
    """Every usable fixture, extracted and aligned. Empty when there are none."""
    directory = Path(fixtures_dir or FIXTURES_DIR)
    if not directory.exists():
        return []

    cases: list[Case] = []
    for golden_path in sorted(directory.glob(f"*{GOLDEN_SUFFIX}")):
        golden = _read_golden(golden_path)

        pdf_path = directory / golden.source_pdf
        if not pdf_path.exists():
            raise FixtureError(
                f"{golden_path.name} names source_pdf {golden.source_pdf!r}, which "
                f"is not in {directory}.\n"
                "Fixture PDFs are gitignored by default — real invoices carry names, "
                "addresses and amounts — so a fresh clone has goldens with no "
                "documents beside them. Put the PDF back, or delete the golden."
            )

        outcome = run_extraction(pdf_path, refresh=refresh)
        alignment = align(
            outcome.transactions,
            [item.model_dump() for item in golden.line_items],
        )
        cases.append(
            Case(
                name=golden_path.name[: -len(GOLDEN_SUFFIX)],
                pdf_path=pdf_path,
                golden_path=golden_path,
                golden=golden,
                outcome=outcome,
                alignment=alignment,
            )
        )

    _warn_on_coverage_gaps(cases)
    return cases


def _warn_on_coverage_gaps(cases: list[Case]) -> None:
    """Say what the fixture set cannot currently prove."""
    if not cases:
        return

    scored = [case for case in cases if case.golden.expect_error is None]
    if scored and not any(case.golden.rounding_divergent for case in scored):
        warnings.warn(
            "No fixture has rounding_divergent set, so metrics/totals.py cannot "
            "actually demonstrate the rule it exists to protect: on these invoices "
            "round-each-then-sum and sum-then-round agree, so a regression to the "
            "wrong one would score green. Add an invoice whose line totals have "
            "fractional cents (docs/domain.md's example is three lines of "
            "0.25 x 0.50).",
            stacklevel=2,
        )

    if scored and not any(case.golden.ambiguous for case in scored):
        warnings.warn(
            "No fixture marks any field as ambiguous, so ConfidenceCalibration has "
            "an empty recall denominator on every case — it cannot tell you whether "
            "the extractor flags what it misreads. Add an invoice with something "
            "genuinely hard to read (a day-first/month-first date, a struck-through "
            "quantity) and record it in `ambiguous`.",
            stacklevel=2,
        )

    if not any(case.golden.expect_error for case in scored + cases):
        warnings.warn(
            "No fixture expects an error, so the rejection paths are covered only by "
            "test_failure_modes.py's synthetic cases, not by a real document.",
            stacklevel=2,
        )


def load_test_cases(**kwargs) -> list[LLMTestCase]:
    """`load()`, as deepeval test cases."""
    return [case.to_test_case() for case in load(**kwargs)]
