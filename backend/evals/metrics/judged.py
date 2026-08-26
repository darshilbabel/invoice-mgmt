"""The three questions a model has to answer, and nothing else.

A string can be correct in more than one shape — "Acme Pvt. Ltd." and "Acme Private
Limited" are the same company; "Homepage design work" and "Design work - homepage"
are the same line. No amount of string distance settles those, and pretending
otherwise produces a metric that fails on correct extractions.

Everything else stays deterministic. Numbers, dates, counts and set membership are
never put to a model, because a judge that reasons "6,000 and 6000.00 are basically
the same" is the exact bug this suite exists to catch.

## Two invariants, both enforced in code rather than by memory

**1. Every metric names its model.** deepeval autoloads a dotenv from the working
directory; run from `backend/` that supplies OPENAI_API_KEY, and
`initialize_model(None)` prefers OpenAI over everything else. A `GEval(...)` with no
`model=` therefore does not fail — it silently judges with GPT on the application's
own key and reports a normal-looking score. `_geval()` below is the only constructor
in this module and it always passes `model=judge()`; `assert_judged_by_sonnet()`
re-checks it afterwards, so the guarantee does not rest on nobody editing this file
carelessly.

**2. Rubrics are coarse and thresholds have margin.** claude-sonnet-5 removed
`temperature`, so the judge cannot be pinned to greedy decoding (see `judge.py`).
Determinism has to come from asking questions whose answer does not sit near a
boundary: "same entity, yes or no", not "rate the similarity out of ten". Each metric
below states its criteria as a small number of discrete cases for that reason.

**3. Rubrics never name a number.** Not a style preference — a bug, found on
2026-08-25 and fixed the same day.

GEval asks its judge for a score on a **0-10** scale and divides by ten. These
rubrics used to be written in 0.0-1.0 language: *"Score 1.0 if they name the same
billable item."* So "the same item" had two defensible answers, `10` (the harness's
scale) and `1` (the rubric's literal instruction), and the judge picked between them
run to run. `1/10` is `0.10`, which is below every threshold here — so a correct
extraction failed roughly half the time, with a written reason saying the two texts
were identical. Score and reason contradicting each other is the signature.

The failure was invisible for two compounding reasons. It is bimodal at exactly
`0.10` and `1.00` rather than noisy around a mean, so a single measurement looks
like a clean verdict rather than a wobble; and `evals/README.md` § "Thresholds are
provisional" invites reading any judged failure as a threshold that needs
calibrating, which is the one explanation that would never have led here.

So: say "award the maximum score" and "award the minimum score", never "1.0" and
"0.0". A rubric that names a number is naming it on a scale it cannot see.
`evals/report.py` measures each judged metric several times and prints every
sample, which is what makes a relapse visible as **unstable** rather than as a
failed extraction.

## What the judge is given

Never the whole payload. Each metric gets one short, single-aspect comparison built
by `evals/derived.py` from pairs the deterministic layer has *already* matched. A
judge handed a JSON blob and asked "is this right" is being asked to do the whole
suite's job in one call, badly and expensively.
"""

from __future__ import annotations

from deepeval.metrics import GEval
from deepeval.test_case import SingleTurnParams

from evals.judge import judge, judge_name

#: Provisional. Real values come from a baseline over real invoices — see README.
DEFAULT_THRESHOLD = 0.7


def _geval(*, name: str, steps: list[str], params: list[SingleTurnParams], threshold: float) -> GEval:
    """The only place a judged metric is constructed. Always names the model."""
    return GEval(
        name=name,
        evaluation_steps=steps,
        evaluation_params=params,
        model=judge(),  # never omit — see invariant 1 in the module docstring
        threshold=threshold,
        # Binary scoring would throw away the judge's uncertainty, which on a model
        # without temperature control is information worth keeping.
        strict_mode=False,
    )


def assert_judged_by_sonnet(*metrics) -> None:
    """Fail if any metric is not actually using the Anthropic judge.

    The failure this catches is silent by construction: a metric that fell back to
    OpenAI produces scores, fills a report, and bills a key — nothing in the output
    says which model graded the run.
    """
    expected = judge_name()
    for metric in metrics:
        actual = getattr(metric, "evaluation_model", None)
        if actual != expected:
            raise AssertionError(
                f"{getattr(metric, 'name', metric)!r} is being judged by {actual!r}, "
                f"not {expected!r}.\n"
                "This is the silent-swap failure: deepeval autoloads backend's "
                "dotenv, which carries OPENAI_API_KEY, and initialize_model(None) "
                "prefers OpenAI. A judged metric built without an explicit "
                "model=judge() quietly grades with GPT on the application's key. "
                "Construct it through _geval() in evals/metrics/judged.py."
            )


def description_equivalence(threshold: float = DEFAULT_THRESHOLD) -> GEval:
    """Do two line-item descriptions name the same thing.

    Asked only about pairs `align.py` has already matched, and only about the text —
    the quantity and unit price of those same rows are compared exactly, by
    `lines.LineItemNumerics`, and are none of the judge's business.
    """
    return _geval(
        name="Line description equivalence",
        steps=[
            "Both texts are descriptions of the same row of an invoice's line-item "
            "table. Decide whether they describe the same billable thing.",
            "Reordered words, punctuation, abbreviation, capitalisation and extra "
            "detail that does not change what was billed are all the same thing. "
            "'Homepage design work' and 'Design work - homepage' are the same.",
            # Scale-free wording — no literal numbers. See "Rubrics never name a
            # number" in the module docstring.
            "Award the maximum score if they name the same billable item. Award the "
            "minimum score if they name different items, or if one names a service "
            "and the other a product, or if one is a subtotal or tax row rather "
            "than a line item.",
            "Do not consider amounts, quantities or prices even if they appear in "
            "the text — they are checked separately and exactly.",
        ],
        params=[SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT],
        threshold=threshold,
    )


def customer_identity(threshold: float = DEFAULT_THRESHOLD) -> GEval:
    """Is the extracted party the same real-world entity as the one billed.

    The positive half of the party check. The negative half — that it is not the
    *issuer* — is deterministic, is scored at threshold 1.0, and is the half with
    the permanent consequence. See `metrics/direction.py`.
    """
    return _geval(
        name="Customer identity",
        steps=[
            "Both texts describe the party an invoice is addressed to: a company "
            "name, and possibly an email address and a postal address.",
            "Decide whether they refer to the same real-world organisation.",
            "Legal-form suffixes are noise: 'Acme Pvt. Ltd.', 'Acme Private "
            "Limited' and 'Acme' are the same organisation. So are differences in "
            "abbreviation, punctuation, line breaks and address formatting.",
            # Scale-free wording — no literal numbers. See "Rubrics never name a
            # number" in the module docstring. The middle case is the one that was
            # most badly served by the old wording: "score around 0.5" read on
            # GEval's 0-10 scale is 0.05, which is below this metric's own
            # threshold — a right-company-wrong-address match scored the same as a
            # different company entirely.
            "Award the maximum score if it is the same organisation at the same "
            "address. Award a score halfway between the maximum and the minimum if "
            "the organisation matches but the contact details belong to somewhere "
            "else. Award the minimum score if they are different organisations, or "
            "if one is empty.",
        ],
        params=[SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT],
        threshold=threshold,
    )


def notes_grounding(threshold: float = DEFAULT_THRESHOLD) -> GEval:
    """Is everything in `notes` actually printed on the page.

    Framed as grounding rather than accuracy, deliberately. `extraction.PROMPT`
    never mentions `notes`, and `SCHEMA` declares it as a bare `{"type": "string"}`
    with no description — the field is entirely undefined, so there is nothing for
    it to be *accurate to*. That is precisely why it is the field most free to
    hallucinate, and why "nothing in it may be absent from the page" is the right
    and only question. (That `notes` is undefined in the prompt is a finding about
    the system under test, not something this suite should paper over.)
    """
    return _geval(
        name="Notes grounding",
        steps=[
            "The 'actual output' is a notes field an extractor produced from an "
            "invoice. The 'expected output' is the text actually printed on that "
            "invoice outside its line-item table.",
            "Decide whether every statement in the notes is supported by the "
            "printed text. You are checking for invented content, not for "
            "completeness — omitting something is fine.",
            # Scale-free wording — no literal numbers. See "Rubrics never name a
            # number" in the module docstring.
            "Award the maximum score if the notes are empty, or if everything in "
            "them appears in the printed text (rewording is fine). Award the "
            "minimum score if the notes assert anything, however plausible, that "
            "is not on the page.",
            "Payment terms, bank details and dates are the usual inventions. Treat "
            "a plausible-but-absent term as a failure, not as a reasonable summary.",
        ],
        params=[SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT],
        threshold=threshold,
    )


def all_judged(threshold: float = DEFAULT_THRESHOLD) -> dict:
    """The three judged metrics, verified to be on the Anthropic judge."""
    metrics = {
        "description_equivalence": description_equivalence(threshold),
        "customer_identity": customer_identity(threshold),
        "notes_grounding": notes_grounding(threshold),
    }
    assert_judged_by_sonnet(*metrics.values())
    return metrics
