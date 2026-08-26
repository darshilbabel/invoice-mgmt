"""Matching extracted line items to golden ones. Deterministic, computed once.

Every metric that touches line items reads this module's output. It is computed in
`dataset.py` and stashed on the test case, never recomputed — two metrics
independently guessing an alignment will eventually disagree, and that disagreement
looks exactly like a bug in the extractor.

## Why not index order

Because the likeliest real failure is an inserted row. The prompt explicitly forbids
importing a `Subtotal` or tax row as a line item, which is precisely the sign that it
happens. Under index matching, one inserted row at position 2 misaligns every row
after it: a single error reports as N failures, and the score tells you nothing about
what actually went wrong. Maximally uninformative about the most likely fault.

## Why not an LLM

Because it would make this suite's central rule false through the back door. The rule
is that numbers are never judged by a model. A judge that decides *which* golden line
an extracted row corresponds to has already decided whether that row's numbers are
wrong — it just did it invisibly, inside a matching step nobody is scoring.

## What it does instead — two stages, stdlib only

1. **Exact numeric signature.** Match on `(quantity, unit_price)` as a 2dp string
   pair, greedily over the multiset. Both sides are already normalised to 2dp
   strings, so this is unambiguous and free. It also means the rows the extractor got
   *right* are matched before any fuzzy reasoning happens, which is what leaves the
   interesting failures visible in stage 2.
2. **Description similarity, on the leftovers only.** `difflib.SequenceMatcher` over
   casefolded, punctuation-stripped descriptions, best-pair-first above a floor. This
   is what catches the row whose description was read correctly but whose money was
   not — the money bug, isolated with its description as evidence.

Anything still unmatched is a real miss (golden row not found) or a real spurious row
(extracted row corresponding to nothing on the page).

No scipy. N is 1-20 line items; greedy-descending over the pair scores is optimal
often enough and cheap always, and a dependency for this would be absurd.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Two rows are the same row if they share a real word and read similarly, OR if
# they read *very* similarly. Both halves are needed, and the reason is a concrete
# failure this caught: character-level similarity alone rates "Consulting" against
# "Hosting" at 0.71, purely on the shared "-sting"/"-osting" tail. Above a plain 0.6
# floor that becomes a match, and an invented line item then reports as "this row's
# numbers were misread" instead of "this row is not on the invoice" — the wrong
# diagnosis, on the metric that matters most.
#
# Sharing an actual word is the evidence that survives rewording; character ratio
# alone is a suffix artifact on the short strings invoice descriptions tend to be.
DESCRIPTION_FLOOR = 0.6
#: Enough on its own, for descriptions too short to tokenise usefully ("2026-03").
DESCRIPTION_STRONG = 0.85
#: Shorter tokens ("of", "the", "hr") carry no evidence and match by accident.
MIN_TOKEN_LENGTH = 3
#: Word-overlap, which survives reordering where character ratio does not:
#: "Homepage design work" vs "Design work - homepage" is the same line item and
#: shares every word, but scores only 0.55 character-wise because the words moved.
#: That pairing is the canonical case for the description judge, so alignment has
#: to be able to reach it.
TOKEN_OVERLAP_FLOOR = 0.6

_NOT_ALNUM = re.compile(r"[^0-9a-z]+")


def normalise_description(text: object) -> str:
    """Casefold and strip everything but alphanumerics.

    "Design work - homepage" and "design work, homepage." collapse to the same
    string. This is deliberately blunt: it is a *matching* aid, not a judgement
    about whether two descriptions mean the same thing. That question is the
    judge's, and it is asked in `metrics/judged.py` about pairs this module has
    already matched.
    """
    return _NOT_ALNUM.sub(" ", str(text or "").casefold()).strip()


def description_similarity(a: object, b: object) -> float:
    """0.0-1.0 similarity between two descriptions."""
    left, right = normalise_description(a), normalise_description(b)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _tokens(text: object) -> set[str]:
    """Words worth treating as evidence — see MIN_TOKEN_LENGTH."""
    return {
        word
        for word in normalise_description(text).split()
        if len(word) >= MIN_TOKEN_LENGTH
    }


def token_overlap(a: object, b: object) -> float:
    """Jaccard overlap of the two descriptions' significant words.

    Order-insensitive, which is the whole point — see TOKEN_OVERLAP_FLOOR.
    """
    left, right = _tokens(a), _tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def match_score(a: object, b: object) -> float:
    """How strongly two descriptions look like the same row, 0.0-1.0.

    The better of character similarity and word overlap: each catches what the
    other misses. Character ratio handles a reworded or extended description
    ("Hosting" -> "Hosting (annual)"); word overlap handles a reordered one.
    """
    return max(description_similarity(a, b), token_overlap(a, b))


def is_same_row(a: object, b: object, ratio: float | None = None) -> bool:
    """Whether two descriptions plausibly name the same line item.

    A matching *gate*, not a judgement about meaning — that question goes to the
    judge in `metrics/judged.py`, and only about pairs this has already matched.
    """
    if ratio is None:
        ratio = description_similarity(a, b)
    if ratio >= DESCRIPTION_STRONG:
        return True
    if token_overlap(a, b) >= TOKEN_OVERLAP_FLOOR:
        return True
    # Below the strong bar, character similarity needs a shared real word behind
    # it, or "Consulting"/"Hosting" gets through on a shared tail.
    return ratio >= DESCRIPTION_FLOOR and bool(_tokens(a) & _tokens(b))


def _signature(row: dict) -> tuple[str, str]:
    return (str(row.get("quantity") or ""), str(row.get("unit_price") or ""))


def _money_matches(extracted: dict, golden: dict) -> bool:
    return _signature(extracted) == _signature(golden)


@dataclass
class Pair:
    """One extracted row matched to one golden row."""

    extracted_index: int
    golden_index: int
    extracted: dict
    golden: dict
    #: How the pair was established — "numeric" (stage 1) or "description" (stage 2).
    via: str
    description_similarity: float

    @property
    def money_matches(self) -> bool:
        return _money_matches(self.extracted, self.golden)


@dataclass
class Alignment:
    """The result: three buckets, not one score.

    Collapsing these into a single number would hide the distinction that matters
    most. A row matched by description whose money is wrong is *the money bug*; a
    row that matched nothing is a reading failure. They call for different
    responses and they are counted separately.
    """

    #: Description and money both agree. The good case.
    exact: list[Pair] = field(default_factory=list)
    #: The same row, read with the wrong numbers. The expensive case.
    numeric_errors: list[Pair] = field(default_factory=list)
    #: Golden rows nothing was matched to — the extractor missed them.
    missed: list[int] = field(default_factory=list)
    #: Extracted rows matching no golden row — invented, merged, or a summary row.
    spurious: list[int] = field(default_factory=list)

    @property
    def pairs(self) -> list[Pair]:
        return self.exact + self.numeric_errors

    @property
    def order_preserved(self) -> bool:
        """True when matched rows appear in the same relative order on both sides.

        Reported as a sub-signal rather than its own metric. Row order is not part
        of the API contract, but reordering is the observable proxy for the merge
        and split failures the prompt explicitly forbids — worth surfacing, not
        worth failing a run over on its own.
        """
        by_extracted = sorted(self.pairs, key=lambda p: p.extracted_index)
        golden_order = [p.golden_index for p in by_extracted]
        return golden_order == sorted(golden_order)

    def summary(self) -> dict:
        """A small dict for reports and failure messages."""
        return {
            "exact": len(self.exact),
            "numeric_errors": len(self.numeric_errors),
            "missed": len(self.missed),
            "spurious": len(self.spurious),
            "order_preserved": self.order_preserved,
        }


def align(extracted: list[dict], golden: list[dict]) -> Alignment:
    """Match extracted line items to golden line items. Pure; no I/O, no model."""
    extracted = list(extracted or [])
    golden = list(golden or [])

    unmatched_extracted = set(range(len(extracted)))
    unmatched_golden = set(range(len(golden)))
    pairs: list[Pair] = []

    # --- stage 1: exact numeric signature ---------------------------------
    # Walk in order so that when an invoice legitimately repeats a (qty, price)
    # pair - two rows of "1.00 x 50.00" - the first extracted row takes the first
    # golden row. Any pairing of identical signatures is equally correct; going in
    # order just keeps `order_preserved` meaningful.
    for e_index in sorted(unmatched_extracted):
        signature = _signature(extracted[e_index])
        match = next(
            (g for g in sorted(unmatched_golden) if _signature(golden[g]) == signature),
            None,
        )
        if match is not None:
            pairs.append(
                Pair(
                    extracted_index=e_index,
                    golden_index=match,
                    extracted=extracted[e_index],
                    golden=golden[match],
                    via="numeric",
                    description_similarity=description_similarity(
                        extracted[e_index].get("description"),
                        golden[match].get("description"),
                    ),
                )
            )
            unmatched_extracted.discard(e_index)
            unmatched_golden.discard(match)

    # --- stage 2: description similarity, leftovers only -------------------
    # Ranked on match_score (the better of character similarity and word overlap)
    # so a reordered description is reachable at all; the gate below then decides.
    candidates = sorted(
        (
            (
                match_score(
                    extracted[e].get("description"), golden[g].get("description")
                ),
                e,
                g,
            )
            for e in unmatched_extracted
            for g in unmatched_golden
        ),
        key=lambda triple: (-triple[0], triple[1], triple[2]),
    )
    for score, e_index, g_index in candidates:
        if score < DESCRIPTION_FLOOR:
            break  # sorted descending, so nothing below here can qualify either
        if e_index not in unmatched_extracted or g_index not in unmatched_golden:
            continue
        e_description = extracted[e_index].get("description")
        g_description = golden[g_index].get("description")
        # No `ratio=` argument: `score` here is match_score, not the character
        # ratio is_same_row's third parameter means. Letting it recompute costs
        # nothing at this N and keeps the two from drifting into disagreement.
        if not is_same_row(e_description, g_description):
            continue
        pairs.append(
            Pair(
                extracted_index=e_index,
                golden_index=g_index,
                extracted=extracted[e_index],
                golden=golden[g_index],
                via="description",
                # The character ratio, not match_score — this is reported to a
                # human reading a failure, and should mean one plain thing.
                description_similarity=description_similarity(
                    e_description, g_description
                ),
            )
        )
        unmatched_extracted.discard(e_index)
        unmatched_golden.discard(g_index)

    result = Alignment(
        missed=sorted(unmatched_golden),
        spurious=sorted(unmatched_extracted),
    )
    for pair in sorted(pairs, key=lambda p: p.extracted_index):
        (result.exact if pair.money_matches else result.numeric_errors).append(pair)
    return result
