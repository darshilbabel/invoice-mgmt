"""Single-aspect test cases for the judge, built from what alignment already decided.

The judged metrics never see a whole payload. Each gets one short comparison — two
line descriptions, two customer blocks, a notes field against the page text — because
that is the shape GEval scores reliably, and because handing a judge a JSON blob and
asking "is this right" is asking it to redo the entire suite in one call.

It is also where the cost lives. One case per matched line pair, plus one per fixture
for identity and grounding: on a five-line invoice that is seven judge calls, each
one a couple of sentences. The alternative — one call per fixture over the full
payload — is fewer calls carrying far more tokens and returning one number that
cannot tell you which line was wrong.

Nothing here decides *which* rows correspond to which; `align.py` did that
deterministically, before any model was involved. See its docstring for why that
ordering is not negotiable.
"""

from __future__ import annotations

from deepeval.test_case import LLMTestCase


def _party_text(name, email, address) -> str:
    """One party, as a short block — the form the identity judge is prompted on."""
    lines = [str(name or "").strip()]
    if email:
        lines.append(str(email).strip())
    if address:
        lines.append(" ".join(str(address).split()))
    return "\n".join(part for part in lines if part)


def description_pairs(case) -> list[LLMTestCase]:
    """One case per matched line pair — the text only, never the money."""
    cases = []
    for pair in case.alignment.pairs:
        cases.append(
            LLMTestCase(
                name=f"{case.name} · line {pair.golden_index}",
                input="Do these two invoice line descriptions name the same billable item?",
                actual_output=str(pair.extracted.get("description") or ""),
                expected_output=str(pair.golden.get("description") or ""),
                metadata={"case": case, "pair": pair},
            )
        )
    return cases


def customer_pair(case) -> LLMTestCase | None:
    """One case per fixture — extracted party against the golden's bill-to.

    None when the invoice addresses nobody, or when nothing came back: "is this the
    same organisation" has no content in either situation, and both are already
    scored deterministically by `metrics/direction.py`.
    """
    if case.golden.customer_absent:
        return None
    guess = case.payload.get("customer_guess")
    if not guess:
        return None

    bill_to = case.golden.bill_to
    return LLMTestCase(
        name=f"{case.name} · customer",
        input="Do these describe the same organisation?",
        actual_output=_party_text(
            guess.get("name"), guess.get("email"), guess.get("billing_address")
        ),
        expected_output=_party_text(bill_to.name, bill_to.email, bill_to.address),
        metadata={"case": case},
    )


def notes_pair(case) -> LLMTestCase | None:
    """One case per fixture — the notes field against the page's own text.

    None in two cases, for two different reasons.

    **No `notes_source_text` in the golden.** Nothing to be grounded in, so scoring
    grounding would mark every non-empty notes field as hallucinated — a fixture
    gap, not an extraction failure.

    **The extractor returned no notes.** `notes_grounding`'s own rubric says empty
    notes score 1.0: an empty field cannot invent anything, so there is no question
    to put to the judge. Returning a case anyway does not merely waste a call, it
    *raises* — deepeval's `check_llm_test_case_params` rejects an empty
    `actual_output` before GEval ever reaches the rubric, with
    `MissingTestCaseParamsError`. That aborts the run rather than skipping the
    metric, so every fixture whose invoice has no notes section would take the
    whole suite down with it.
    """
    if not case.golden.notes_source_text.strip():
        return None
    if not str(case.payload.get("notes") or "").strip():
        return None
    return LLMTestCase(
        name=f"{case.name} · notes",
        input="Is everything in these notes actually printed on the invoice?",
        actual_output=str(case.payload.get("notes") or ""),
        expected_output=case.golden.notes_source_text,
        metadata={"case": case},
    )
