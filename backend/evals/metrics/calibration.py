"""Is `low_confidence` honest — does the extractor warn about what it misreads.

The whole design of the upload flow rests on this. `docs/specs/2026-08-ocr-ingest.md`
open question 3 settled it as *"fill the field and mark it; never blank, never
refused"*, and `docs/design-tokens.md` spends the app's only use of amber on it: a
low-confidence field is the single signal in the product that is *"genuinely neither
neutral nor an error"*. The counter that says "3 fields need a look" is only worth
reading if those are the three fields that need looking at.

So two numbers:

- **recall** — of the fields the extractor got wrong, how many did it flag. This is
  the one to watch. A flagged wrong field costs the reviewer a glance. An unflagged
  wrong field is a confident, plausible, wrong number that ships.
- **precision** — of the fields it flagged, how many deserved it. Cheap to game by
  flagging everything, which is why the amber counter would stop meaning anything.

## Two confounds, both of which would make this metric decorative

**1. `_normalise` adds flags of its own.** The `low_confidence` list that comes back
is the *union* of what the model flagged and what `extraction._normalise` flagged
after the fact — unparseable money, non-ISO dates. Those normaliser flags are correct
by construction: the value genuinely could not be parsed. Counting them as the
model's would push precision toward a ceiling that says nothing about the model.

They can be separated exactly, because `_normalise` attaches two literal notes. Those
literals are copied below and **guarded**: `assert_normaliser_notes_unchanged()`
checks they still appear in the function's source. Reword one in `extraction.py` and
this fails loudly, rather than silently reclassifying every normaliser flag as a
model flag and quietly inflating precision from that day forward.

**2. Recall is only meaningful over fields the page is genuinely ambiguous about.**
A field the model got wrong that was perfectly legible should have been *right*, not
flagged — treating it as "should have been flagged" rewards flagging everything and
punishes an extractor that simply reads well. So the recall denominator is
`wrong AND listed in the fixture's `ambiguous` map`; a wrong-but-legible field is a
plain extraction error, counted by `scalars.py` and `lines.py`, and excluded here.
"""

from __future__ import annotations

import inspect

from evals.metrics.base import DeterministicMetric, Result, ratio

#: Verbatim from extraction._normalise. A flag carrying one of these came from the
#: normaliser, not the model. Both are attached with `setdefault`, so a model-supplied
#: note for the same path wins — which under-counts normaliser flags slightly, and
#: only ever in the direction of crediting the model less. Acceptable.
NORMALISER_NOTES = (
    "Could not be read as a number — check it against the PDF.",
    "Not a recognisable date — check it against the PDF.",
)


def assert_normaliser_notes_unchanged() -> None:
    """Fail loudly if `_normalise`'s note strings have been reworded.

    This metric identifies normaliser-originated flags by their note text. If that
    text changes and this is not updated, every normaliser flag silently becomes a
    "model flag" and precision inflates for reasons nobody will connect to a
    one-word edit in extraction.py months earlier.
    """
    from billing import extraction

    source = inspect.getsource(extraction._normalise)
    missing = [note for note in NORMALISER_NOTES if note not in source]
    if missing:
        raise AssertionError(
            "extraction._normalise no longer contains the note text this metric "
            "uses to tell normaliser-originated low_confidence flags from "
            "model-originated ones:\n  "
            + "\n  ".join(repr(note) for note in missing)
            + "\n\nUpdate NORMALISER_NOTES in evals/metrics/calibration.py to match. "
            "Left unfixed, those flags would be miscounted as the model's and "
            "precision would read higher than it is."
        )


def _model_flags(payload: dict) -> set[str]:
    """The flags the model raised, with the normaliser's own filtered out."""
    flags = set(payload.get("low_confidence") or [])
    notes = payload.get("field_notes") or {}
    return {path for path in flags if notes.get(path) not in NORMALISER_NOTES}


def wrong_paths(case) -> set[str]:
    """Field paths where the extraction disagrees with the golden.

    Uses the same path grammar `low_confidence` uses, so this is directly
    intersectable with the flags. Line-item paths are indexed by the position in
    the *extracted* list, because that is what the model's flags refer to.
    """
    payload, golden = case.payload, case.golden
    wrong: set[str] = set()

    for key, expected in (
        ("issue_date", golden.issue_date),
        ("due_date", golden.due_date),
        ("source_invoice_number", golden.source_invoice_number),
        ("printed_total", golden.printed_total),
    ):
        if key == "printed_total" and expected is None and not golden.printed_total_absent:
            continue  # the golden takes no position; see scalars.py
        actual = payload.get(key)
        if (expected or None) != (actual or None):
            wrong.add(key)

    # A matched row whose money is wrong: the specific cells are wrong, not the row.
    for pair in case.alignment.numeric_errors:
        index = pair.extracted_index
        if pair.extracted.get("quantity") != pair.golden.get("quantity"):
            wrong.add(f"transactions.{index}.quantity")
        if pair.extracted.get("unit_price") != pair.golden.get("unit_price"):
            wrong.add(f"transactions.{index}.unit_price")

    # A row that corresponds to nothing on the page is wrong in every cell.
    for index in case.alignment.spurious:
        wrong.add(f"transactions.{index}.description")

    return wrong


class ConfidenceCalibration(DeterministicMetric):
    """Does the extractor flag what it gets wrong, without flagging everything."""

    name = "Confidence calibration"

    def __init__(self, threshold: float = 1.0):
        super().__init__(threshold=threshold)
        assert_normaliser_notes_unchanged()

    def evaluate(self, case) -> Result:
        flagged = _model_flags(case.payload)
        wrong = wrong_paths(case)
        ambiguous = set(case.golden.ambiguous)

        # Recall denominator: wrong AND genuinely hard to read. See the docstring.
        should_have_flagged = wrong & ambiguous
        caught = should_have_flagged & flagged
        recall = ratio(len(caught), len(should_have_flagged))

        # A flag is deserved if the field is actually wrong, or if the page really
        # is ambiguous there — flagging a hard-to-read field that was nonetheless
        # read correctly is exactly the behaviour the amber marker is for.
        deserved = flagged & (wrong | ambiguous)
        precision = ratio(len(deserved), len(flagged))

        # Recall weighted heavier: an unflagged wrong field ships a wrong invoice;
        # an over-flagged right field costs a glance.
        score = 0.7 * recall + 0.3 * precision

        parts: list[str] = []
        missed = sorted(should_have_flagged - flagged)
        if missed:
            parts.append(
                "WRONG AND UNFLAGGED (the reviewer gets no reason to look): "
                + ", ".join(missed)
            )
        elif should_have_flagged:
            parts.append(
                f"flagged all {len(should_have_flagged)} of the fields it misread "
                "on ambiguous parts of the page"
            )
        else:
            parts.append(
                "nothing was both misread and marked ambiguous in the fixture, so "
                "recall has no denominator on this invoice"
            )

        undeserved = sorted(flagged - (wrong | ambiguous))
        if undeserved:
            parts.append(
                "flagged but correct and legible: " + ", ".join(undeserved)
            )

        silent = sorted(wrong - flagged - ambiguous)
        if silent:
            # Not scored here — these are plain reading errors that scalars.py and
            # lines.py already count. Surfaced because a run where the extractor is
            # confidently wrong about legible fields is worth seeing in one place.
            parts.append(
                f"(also wrong but legible, so not a calibration failure: "
                + ", ".join(silent)
                + ")"
            )

        return Result(
            score=score,
            reason=f"recall {recall:.0%}, precision {precision:.0%}. " + ". ".join(parts),
            detail={
                "model_flags": sorted(flagged),
                "wrong": sorted(wrong),
                "ambiguous": sorted(ambiguous),
                "recall": recall,
                "precision": precision,
            },
        )
