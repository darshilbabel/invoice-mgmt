"""The scored suite. One row per invoice, plus the judged comparisons.

    deepeval test run evals/test_extraction_eval.py          # everything
    pytest evals/test_extraction_eval.py -m "not judged"     # deterministic only, free

Running it with no fixtures collects and skips cleanly, on purpose: the harness has
to be demonstrably working before there is anything to measure, or the first real
fixture is debugging two things at once.

## Cost

One OpenAI call per fixture on a cold cache, nothing on a warm one — `runner.py`
caches on the PDF, the model, the prompt and the schema together, so a prompt edit
re-runs and a metric edit does not. Set `EVAL_REFRESH=1` to re-extract deliberately.

The judged tests add roughly one short Anthropic call per matched line item plus two
per fixture. They are marked `judged` so they can be deselected; the deterministic
half is the majority of the signal and costs nothing beyond the extraction.
"""

from __future__ import annotations

import pytest
from deepeval import assert_test

from evals.dataset import load
from evals.derived import customer_pair, description_pairs, notes_pair
from evals.metrics import deterministic_metrics
from evals.metrics.judged import (
    assert_judged_by_sonnet,
    customer_identity,
    description_equivalence,
    notes_grounding,
)


def _cases():
    """Fixtures that produced a payload. Rejection fixtures are tested elsewhere.

    Loaded at import so pytest can parametrise over them. A fixture problem raises
    here — a broken golden stops collection rather than silently shrinking the run.
    """
    try:
        return [case for case in load() if case.golden.expect_error is None]
    except Exception as exc:  # noqa: BLE001 - surfaced as a collection error
        pytest.fail(f"fixtures could not be loaded:\n{exc}", pytrace=False)


CASES = _cases()

_ids = [case.name for case in CASES]

skip_without_fixtures = pytest.mark.skipif(
    not CASES,
    reason="no fixtures yet — drop a PDF in evals/fixtures/ and run "
    "`python -m evals.scaffold`. See evals/fixtures/README.md.",
)


@skip_without_fixtures
@pytest.mark.billable
@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_extraction(case):
    """Every deterministic metric, against one invoice.

    These are the metrics that can fail for a reason you can act on without reading
    a model's opinion: wrong money, the wrong party, a missing row, a summary row
    imported as a line item, a flag pointing at nothing.
    """
    assert_test(case.to_test_case(), deterministic_metrics())


@skip_without_fixtures
@pytest.mark.judged
@pytest.mark.billable
@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_line_descriptions_mean_the_same_thing(case):
    """Judged, on pairs alignment already matched — text only, never the money."""
    pairs = description_pairs(case)
    if not pairs:
        pytest.skip("no line items matched; see the fidelity metric")

    metric = description_equivalence()
    assert_judged_by_sonnet(metric)
    for test_case in pairs:
        assert_test(test_case, [metric])


@skip_without_fixtures
@pytest.mark.judged
@pytest.mark.billable
@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_customer_is_the_right_organisation(case):
    """The positive half of the party check.

    The negative half — that it is not the *issuer* — is deterministic, scored at
    threshold 1.0 in `metrics/direction.py`, and is the half that writes a permanent
    row when it fails. This one only allows for "Acme Pvt. Ltd." vs "Acme Private
    Limited" being the same company.
    """
    test_case = customer_pair(case)
    if test_case is None:
        pytest.skip("no party addressed, or none returned — covered deterministically")

    metric = customer_identity()
    assert_judged_by_sonnet(metric)
    assert_test(test_case, [metric])


@skip_without_fixtures
@pytest.mark.judged
@pytest.mark.billable
@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_notes_are_grounded_in_the_page(case):
    """`notes` is undefined in the prompt, so the only fair question is invention."""
    test_case = notes_pair(case)
    if test_case is None:
        pytest.skip("nothing to ground: the golden records no page text, or the extractor returned no notes")

    metric = notes_grounding()
    assert_judged_by_sonnet(metric)
    assert_test(test_case, [metric])
