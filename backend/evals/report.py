"""Runs the full metric set over named fixtures and writes one markdown report.

    python -m evals.report 100_poor_crop_right 101_poor_crop_corner -o eval-report.md

`deepeval test run` already prints a table. This exists because that table is
per-assertion and transient, and the question being asked here is per-document:
*how did the extractor do on this PDF, across every metric family we have.*

Three families run, and the report keeps them apart because they cost and mean
different things:

1. **Deterministic** — `metrics/deterministic_metrics()`. No model, no cost. The
   money, the parties, the rows.
2. **Tool correctness** — deepeval's `ToolCorrectnessMetric` over the real stage
   trace from `trace.py`. No model, no cost. Did the pipeline take the whole path.
3. **Judged** — `claude-sonnet-5`, via `metrics/judged.py` for the three string
   questions, plus deepeval's `AnswerRelevancyMetric` for whether the returned
   payload actually answers what was asked of it.

`AnswerRelevancyMetric` is passed `model=judge()` for the same reason every metric
in `judged.py` is: deepeval autoloads backend's dotenv, `initialize_model(None)`
prefers OpenAI, and a judged metric built without an explicit model silently grades
with GPT on the application's own key. It is not built through `_geval()` because it
is not a GEval subclass — the README's greppable invariant matches the GEval
constructor specifically, and it still holds. (Worded without that literal so this
docstring does not itself become a hit in that grep.)
"""

from __future__ import annotations

# First, and before anything imports deepeval. See evals/bootstrap.py.
from evals import bootstrap  # noqa: F401  isort:skip

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from deepeval.metrics import AnswerRelevancyMetric, ToolCorrectnessMetric
from deepeval.test_case import LLMTestCase, ToolCall

from evals.dataset import load
from evals.derived import customer_pair, description_pairs, notes_pair
from evals.judge import judge, judge_name
from evals.metrics import deterministic_metrics, rejection_metrics
from evals.metrics.judged import (
    assert_judged_by_sonnet,
    customer_identity,
    description_equivalence,
    notes_grounding,
)
from evals.stability import sample_extractions
from evals.trace import expected_stages, traced_extraction  # noqa: F401

#: The request the extractor is answering, in the words a person would use. Answer
#: relevancy scores the payload against this, so it has to name what was asked for
#: and nothing more — every clause added here is a clause the payload can be marked
#: irrelevant for not addressing.
EXTRACTION_REQUEST = (
    "Read this invoice PDF and return what is printed on it: the party the invoice "
    "is addressed to, the supplier's invoice number, the issue and due dates, every "
    "line item with its description, quantity and unit price, the total printed on "
    "the page, and which of those fields you were unsure about."
)

#: Provisional, like every non-1.0 threshold in this suite. See README § Thresholds.
ANSWER_RELEVANCY_THRESHOLD = 0.7

#: Live extractions per rejection fixture. 0 means "trust the single cached one",
#: which is what the suite did before 2026-08-25 and is how a page that fabricates
#: an invoice four times in ten scored a clean pass. Only applied to fixtures whose
#: golden declares expect_error — that is where "did it refuse" is the whole
#: question. Every sample is a billable call; see evals/stability.py.
EXTRACT_SAMPLES = 8


#: How many times each judged metric is measured. Not a luxury: claude-sonnet-5
#: removed `temperature`, so the judge cannot be pinned to greedy decoding (see
#: evals/judge.py), and a single sample of an unstable metric is a coin flip
#: reported as a verdict. Three is the smallest number that can show a split.
JUDGE_REPEATS = 3


@dataclass
class Score:
    """One metric's verdict on one fixture.

    `samples` holds every measurement taken. Deterministic metrics take one and it
    is the answer. Judged metrics take `JUDGE_REPEATS`, and `score` is their
    **median** — the reported verdict is then what the judge says more often than
    not, rather than whichever way the last call happened to fall.
    """

    family: str
    name: str
    score: float | None
    threshold: float
    passed: bool
    reason: str
    samples: list[float] = field(default_factory=list)

    @property
    def mark(self) -> str:
        return "PASS" if self.passed else "FAIL"

    @property
    def unstable(self) -> bool:
        """True when repeated measurements did not agree on pass/fail."""
        if len(self.samples) < 2:
            return False
        verdicts = {sample >= self.threshold for sample in self.samples}
        return len(verdicts) > 1

    @property
    def spread(self) -> str:
        if len(self.samples) < 2:
            return "—"
        joined = ", ".join(f"{sample:.2f}" for sample in self.samples)
        return f"**unstable** ({joined})" if self.unstable else f"stable ({joined})"


def _repeat(build_metric, test_case, repeats: int = JUDGE_REPEATS):
    """Measure one judged metric `repeats` times. Returns (median, samples, reason).

    A fresh metric per call: deepeval metric objects carry the previous score and
    reason on themselves, and reusing one makes it far too easy to read a stale
    attribute after a call that raised.
    """
    samples: list[float] = []
    reasons: list[str] = []
    threshold = None
    for _ in range(repeats):
        metric = build_metric()
        assert_judged_by_sonnet(metric)
        metric.measure(test_case)
        samples.append(float(metric.score))
        reasons.append(metric.reason or "")
        threshold = metric.threshold
    ordered = sorted(samples)
    median = ordered[len(ordered) // 2]
    # The reason kept is the one belonging to a sample on the reported side of the
    # threshold, so the prose and the verdict cannot contradict each other.
    for sample, reason in zip(samples, reasons):
        if (sample >= threshold) == (median >= threshold):
            return median, samples, reason, threshold
    return median, samples, reasons[-1], threshold


def _payload_as_prose(payload: dict) -> str:
    """The extraction, rendered as sentences, for the relevancy judge.

    Deterministic string building — no model. Answer relevancy works by splitting an
    output into statements and asking whether each addresses the input; handing it a
    JSON blob measures how JSON-shaped the answer is, not whether it answered.
    """
    customer = payload.get("customer_guess") or {}
    lines = payload.get("transactions") or []
    flags = payload.get("low_confidence") or []

    parts = [
        "The invoice is addressed to "
        + (customer.get("name") or "nobody the extractor could identify")
        + (f", at {customer['billing_address']}" if customer.get("billing_address") else "")
        + ".",
        f"The supplier's invoice number is {payload.get('source_invoice_number') or 'not stated'}.",
        f"It was issued on {payload.get('issue_date') or 'an unstated date'}"
        + (f" and is due on {payload['due_date']}." if payload.get("due_date") else
           ", with no due date printed."),
    ]
    if lines:
        parts.append(f"It has {len(lines)} line item(s):")
        for row in lines:
            parts.append(
                f"- {row.get('description') or '(no description)'}: "
                f"quantity {row.get('quantity')} at unit price {row.get('unit_price')}."
            )
    else:
        parts.append("It has no line items.")
    parts.append(
        f"The total printed on the page is {payload.get('printed_total') or 'not printed'}."
    )
    parts.append(
        ("The extractor was unsure about: " + ", ".join(flags) + ".")
        if flags
        else "The extractor was not unsure about any field."
    )
    if payload.get("notes"):
        parts.append(f"Notes on the invoice: {payload['notes']}")
    return "\n".join(parts)


def _tool_calls(names) -> list[ToolCall]:
    return [ToolCall(name=name) for name in names]


def _run_deterministic(case, metrics=None, family: str = "Deterministic") -> list[Score]:
    test_case = case.to_test_case()
    scores = []
    for metric in (metrics if metrics is not None else deterministic_metrics()):
        metric.measure(test_case)
        scores.append(
            Score(
                family=family,
                name=metric.name,
                score=metric.score,
                threshold=metric.threshold,
                passed=bool(metric.is_successful()),
                reason=metric.reason or "",
            )
        )
    return scores


def _run_tool_correctness(case, trace) -> Score:
    expected = expected_stages(case.golden)
    test_case = LLMTestCase(
        name=case.name,
        input=EXTRACTION_REQUEST,
        actual_output=json.dumps(case.payload, sort_keys=True),
        tools_called=_tool_calls(trace.names),
        expected_tools=_tool_calls(expected),
    )
    # Ordering matters here in a way it does not for an agent: these are pipeline
    # stages, and parsing before the model call would be a real defect rather than
    # a stylistic difference.
    #
    # `available_tools=` is deliberately NOT passed, and `evals.trace.ALL_STAGES`
    # exists only to be available if that ever changes. Supplying it switches on
    # ToolCorrectnessMetric's tool-*selection* sub-score, which is judged by a
    # model — it asks whether the chain was a sensible choice from the menu. That
    # is a question about an agent's judgement, and there is no agent here: the
    # stages are straight-line Python that cannot have chosen otherwise.
    #
    # Measured, not assumed. With `available_tools` supplied, the two fixtures in
    # this report produced *identical* traces against *identical* expectations and
    # scored 1.00 and 0.75 — the 0.75 reasoned that `normalise_payload` might be
    # "over-selection". That turns the one free, deterministic metric in the
    # judged half of the suite into noise. Leave it off.
    metric = ToolCorrectnessMetric(threshold=1.0, should_consider_ordering=True)
    metric.measure(test_case)
    return Score(
        family="Tool correctness",
        name="Pipeline stages called",
        score=metric.score,
        threshold=metric.threshold,
        passed=bool(metric.is_successful()),
        reason=(metric.reason or "")
        + f" | expected {list(expected)} | called {trace.names}",
    )


def _run_answer_relevancy(case, repeats: int = JUDGE_REPEATS) -> Score:
    """Does the returned payload actually answer what the extractor was asked for."""

    def build():
        metric = AnswerRelevancyMetric(
            threshold=ANSWER_RELEVANCY_THRESHOLD,
            model=judge(),  # never omit - see the module docstring
            async_mode=False,
        )
        if getattr(metric, "evaluation_model", None) != judge_name():
            raise AssertionError(
                f"Answer relevancy is being judged by {metric.evaluation_model!r}, "
                f"not {judge_name()!r}. See evals/judge.py section 'The silent swap'."
            )
        return metric

    test_case = LLMTestCase(
        name=case.name,
        input=EXTRACTION_REQUEST,
        actual_output=_payload_as_prose(case.payload),
    )
    median, samples, reason, threshold = _repeat(build, test_case, repeats)
    return Score(
        family="Answer relevancy",
        name="Answer relevancy",
        score=median,
        threshold=threshold,
        passed=median >= threshold,
        reason=reason,
        samples=samples,
    )


def _run_judged(case, repeats: int = JUDGE_REPEATS) -> list[Score]:
    """The three string questions plus answer relevancy, each measured `repeats` times."""
    scores: list[Score] = []

    pairs = description_pairs(case)
    if pairs:
        for index, pair in enumerate(pairs):
            median, samples, reason, threshold = _repeat(
                description_equivalence, pair, repeats
            )
            scores.append(
                Score(
                    family="Judged",
                    name=f"Line description equivalence (row {index})",
                    score=median,
                    threshold=threshold,
                    passed=median >= threshold,
                    reason=reason,
                    samples=samples,
                )
            )
    else:
        scores.append(
            Score("Judged", "Line description equivalence", None, 0.7, False,
                  "skipped - no line items matched; see the fidelity metric")
        )

    pair = customer_pair(case)
    if pair is not None:
        median, samples, reason, threshold = _repeat(customer_identity, pair, repeats)
        scores.append(
            Score("Judged", "Customer identity", median, threshold,
                  median >= threshold, reason, samples)
        )

    pair = notes_pair(case)
    if pair is not None:
        median, samples, reason, threshold = _repeat(notes_grounding, pair, repeats)
        scores.append(
            Score("Judged", "Notes grounding", median, threshold,
                  median >= threshold, reason, samples)
        )
    else:
        scores.append(
            Score("Judged", "Notes grounding", None, 0.7, True,
                  "not scored - the extractor returned no notes, and an empty field "
                  "cannot invent anything. See evals/derived.py notes_pair().")
        )

    scores.append(_run_answer_relevancy(case, repeats))
    return scores


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _flatten(text: str) -> str:
    """One line, no tabs. ToolCorrectnessMetric's reason is a multi-line block."""
    return " ".join((text or "").split())


def _fixture_section(case, trace, scores: list[Score]) -> str:
    passed = sum(1 for s in scores if s.passed)
    lines = [
        f"## `{case.pdf_path.name}`",
        "",
        f"- **Fixture** — `{case.name}`, {case.golden.page_count} page, "
        f"golden `{case.golden_path.name}`",
        f"- **Extraction** — {'served from cache' if case.outcome.cached else 'live call'}, "
        f"{case.outcome.duration_seconds:.1f}s, "
        f"{'payload returned' if case.outcome.ok else f'refused - {case.outcome.error_reason}'}"
        + ("" if case.golden.expect_error is None
           else f" (a refusal is the golden's expected outcome)"),
        f"- **Result** — **{passed}/{len(scores)} metrics passed**",
        "",
        "| Family | Metric | Score | Threshold | Verdict | Repeat runs |",
        "|---|---|---|---|---|---|",
    ]
    for score in scores:
        lines.append(
            f"| {score.family} | {score.name} | {_fmt(score.score)} | "
            f"{score.threshold:.2f} | {score.mark} | {score.spread} |"
        )

    lines += ["", "### Why each metric scored what it did", ""]
    for score in scores:
        lines.append(f"**{score.name}** — {score.mark} ({_fmt(score.score)})  ")
        lines.append(_flatten(score.reason) or "(no reason given)")
        lines.append("")

    lines += [
        "### Recorded pipeline trace",
        "",
        "| # | Stage | Detail |",
        "|---|---|---|",
    ]
    for index, stage in enumerate(trace.stages, start=1):
        detail = ", ".join(f"{k}={v}" for k, v in stage.detail.items()) or "—"
        lines.append(f"| {index} | `{stage.name}` | {detail} |")

    lines += [
        "",
        "<details><summary>Extracted payload</summary>",
        "",
        "```json",
        json.dumps(case.payload, indent=2, sort_keys=True),
        "```",
        "",
        "</details>",
        "",
    ]
    return "\n".join(lines)


def build(names: list[str], repeats: int = JUDGE_REPEATS, preamble: str = "",
          extract_samples: int = EXTRACT_SAMPLES) -> str:
    """Run every family over the named fixtures and return the markdown."""
    cases = {case.name: case for case in load()}
    missing = [name for name in names if name not in cases]
    if missing:
        raise SystemExit(
            f"no such fixture(s): {missing}. Available: {sorted(cases)}"
        )

    selected = [cases[name] for name in names]
    sections = []
    summary_rows = []

    for case in selected:
        trace = traced_extraction(case.pdf_path)
        if case.golden.expect_error is not None:
            # Nothing came back, so there is nothing for the payload metrics or the
            # judge to score. What is scorable is that it refused, that it refused
            # for the reason the golden declares, that it invented nothing, and —
            # only visible in the trace — that it refused AFTER looking at the page
            # rather than before. See evals/metrics/rejection.py.
            samples = (
                sample_extractions(case.pdf_path, n=extract_samples)
                if extract_samples
                else None
            )
            scores = _run_deterministic(
                case, rejection_metrics(samples), family="Rejection"
            )
            scores.append(_run_tool_correctness(case, trace))
        else:
            scores = _run_deterministic(case)
            scores.append(_run_tool_correctness(case, trace))
            scores.extend(_run_judged(case, repeats))
        sections.append(_fixture_section(case, trace, scores))
        summary_rows.append(
            (case.pdf_path.name,
             sum(1 for s in scores if s.passed),
             len(scores),
             [s.name for s in scores if not s.passed])
        )

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = [
        "# Extraction eval — negative (degraded) invoice PDFs",
        "",
        f"Run {stamp} · extractor `billing/extraction.py` · "
        f"judge `{judge_name()}`",
        "",
        f"Judged metrics were measured {repeats}x each and report the median; "
        "`claude-sonnet-5` cannot be pinned to greedy decoding, so a single sample "
        "is not a verdict. See evals/judge.py.",
        "",
        "| PDF | Passed | Failed metrics |",
        "|---|---|---|",
    ]
    for name, passed, total, failures in summary_rows:
        header.append(
            f"| `{name}` | {passed}/{total} | "
            + (", ".join(failures) if failures else "none")
            + " |"
        )
    header.append("")

    body = "\n".join(header) + "\n" + "\n---\n\n".join(sections)
    # The preamble is hand-written analysis of a run — what the numbers mean, which
    # findings are about the extractor and which are about the harness. Kept in its
    # own file and passed in so regenerating the mechanical half does not delete it.
    return (preamble.rstrip() + "\n\n---\n\n" + body) if preamble.strip() else body


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("fixtures", nargs="+", help="fixture names, without .expected.json")
    parser.add_argument("-o", "--output", type=Path, help="write markdown here")
    parser.add_argument(
        "--judge-repeats", type=int, default=JUDGE_REPEATS,
        help="times to measure each judged metric (default %(default)s); the "
             "reported score is the median and the samples are printed",
    )
    parser.add_argument(
        "--extract-samples", type=int, default=EXTRACT_SAMPLES,
        help="live extractions per rejection fixture, to measure whether it refuses "
             "reliably (default %(default)s; 0 trusts the single cached extraction). "
             "Samples accumulate in the cache, so raising this tops up rather than "
             "re-billing what is already collected",
    )
    parser.add_argument(
        "--preamble", type=Path,
        help="markdown file to place above the generated tables; hand-written "
             "analysis lives there so regenerating does not overwrite it",
    )
    args = parser.parse_args(argv)

    preamble = args.preamble.read_text() if args.preamble else ""
    markdown = build(args.fixtures, args.judge_repeats, preamble, args.extract_samples)
    if args.output:
        args.output.write_text(markdown)
        print(f"wrote {args.output}")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
