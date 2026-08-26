"""Did the extractor pick the party the invoice is addressed TO.

This is the highest-consequence check in the suite, and the reason is not that the
field is important — it is that the mistake is *permanent*.

`_resolve_customer` in `billing/views.py` matches the extracted party against
`Customer` rows and **creates one when nothing matches**. `Customer` is
`on_delete=PROTECT`. So a run that returns the letterhead instead of the addressee
does not just mis-fill a form: it writes a `Customer` row for the supplier's own
company into the database, where it stays until somebody deletes it by hand from
`/customers`. `docs/specs/2026-08-ocr-ingest.md` open question 4 records this as a
knowing reversal, and `docs/qa-strategy.md` carries "stray Customer rows created by
a misread PDF" as a tracked risk with no automated coverage. This is that coverage.

`extraction.py`'s PROMPT shouts about it in capitals, which is itself evidence that
the model gets it wrong without being told:

    THE CUSTOMER IS THE PARTY THE INVOICE IS ADDRESSED TO [...] It is NOT the party
    issuing the invoice, whose name usually sits at the top as a letterhead. [...]
    never mix one party's name with the other party's contact details.

That last clause is a second, subtler failure and this module checks it separately:
the right company name paired with the supplier's email or postal address. A
`Customer` row created that way looks correct in the list and sends correspondence to
the wrong place.

## Deterministic, threshold 1.0, no judge

Deliberately. "Is this the issuer?" is a question about *which* of two named parties
was returned, and both names are recorded in the fixture — so it is a comparison, not
a judgement, and it should never be delegated to a model or scored on a curve.

The positive half — "is the returned name the same entity as the bill-to, allowing
for 'Acme Pvt. Ltd.' vs 'Acme Private Limited'" — genuinely does need a judge, and
lives in `judged.py`. The two halves do not overlap, and this one is the half with
the permanent consequence.
"""

from __future__ import annotations

import re

from evals.metrics.base import DeterministicMetric, Result

_NOT_ALNUM = re.compile(r"[^0-9a-z]+")

#: Corporate suffixes, stripped before comparing. "SkilloVilla Technologies Pvt Ltd"
#: on the letterhead and "SkilloVilla Technologies" in the payload are the same
#: company, and an issuer check that missed that would pass exactly when it matters.
_SUFFIXES = re.compile(
    r"\b(pvt|private|ltd|limited|llp|llc|inc|incorporated|corp|corporation|co|"
    r"company|gmbh|plc|sa|bv|ag|srl|pte)\b"
)


def _key(value: object) -> str:
    """A comparable form of a company name: casefolded, de-suffixed, alnum only."""
    text = _NOT_ALNUM.sub(" ", str(value or "").casefold())
    text = _SUFFIXES.sub(" ", text)
    return " ".join(text.split())


def _same_entity(a: object, b: object) -> bool:
    left, right = _key(a), _key(b)
    if not left or not right:
        return False
    # Containment as well as equality: "SkilloVilla" against "SkilloVilla
    # Technologies" is the same letterhead read to different lengths.
    return left == right or left in right or right in left


def _same_text(a: object, b: object) -> bool:
    left = " ".join(str(a or "").casefold().split())
    right = " ".join(str(b or "").casefold().split())
    return bool(left) and left == right


class PartyDirection(DeterministicMetric):
    """The extracted party must not be the issuer — name, email or address."""

    name = "Bill-to, not issuer"

    def __init__(self, threshold: float = 1.0):
        # 1.0 and not negotiable: there is no partially-acceptable amount of
        # writing the supplier's own company into the customer table.
        super().__init__(threshold=threshold)

    def evaluate(self, case) -> Result:
        issuer = case.golden.issuer
        guess = case.payload.get("customer_guess") or None

        if case.golden.customer_absent:
            # The page names no addressed party. PROMPT: "If the invoice shows no
            # addressed party at all, return null for customer rather than falling
            # back to the issuer." Returning anything here is the failure.
            if guess is None:
                return Result(
                    score=1.0,
                    reason="no party is addressed on this invoice, and none was "
                    "returned — correct",
                )
            return Result(
                score=0.0,
                reason=(
                    "this invoice addresses no party, so customer should be null, "
                    f"but {guess.get('name')!r} came back. If that is the issuer it "
                    "would be created as a Customer row on upload"
                ),
                detail={"returned": guess},
            )

        if guess is None:
            # Not this metric's failure — a missing customer is a miss, not a
            # wrong-party error. Scored 1.0 here and caught by the identity judge.
            return Result(
                score=1.0,
                reason="no party came back, so nothing was misattributed to the "
                "issuer (whether the right one was found is the identity metric)",
            )

        violations: list[str] = []
        if _same_entity(guess.get("name"), issuer.name):
            violations.append(
                f"name {guess.get('name')!r} is the ISSUER ({issuer.name!r}), not "
                "the party billed — uploading this creates a permanent Customer "
                "row for the supplier's own company"
            )
        if issuer.email and _same_text(guess.get("email"), issuer.email):
            violations.append(
                f"email {guess.get('email')!r} belongs to the issuer — correspondence "
                "would go to the supplier"
            )
        if issuer.address and _same_text(guess.get("billing_address"), issuer.address):
            violations.append(
                f"billing_address is the issuer's — the two parties' details were mixed"
            )

        if not violations:
            return Result(
                score=1.0,
                reason=f"returned {guess.get('name')!r}, which is not the issuer "
                f"({issuer.name!r})",
            )

        return Result(
            score=0.0,
            reason="; ".join(violations),
            detail={"returned": guess, "issuer": issuer.model_dump()},
        )
