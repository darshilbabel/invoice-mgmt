"""The one output-shape check that is actually about the model.

Most of what looks like "does the payload conform to its contract" is *constructed*
by `extraction._normalise` and therefore scores nothing:

- `field_notes` keys being a subset of `low_confidence` is a dict comprehension;
- money always being 2dp is `to_money`'s `quantize`;
- dates always being ISO is `to_date`'s regex gate.

Those are real invariants worth guarding, but they are guards on `_normalise`, not
measurements of the extractor. Scoring them here would add a near-guaranteed 1.0 to
every case and dilute the metrics that can actually fail. They live in
`evals/test_contract.py` instead, as plain pytest, framed as what they are.

What *is* model-facing is the `low_confidence` paths themselves. The model writes
those strings freely, following a grammar described to it in prose, and
`_normalise` does not validate them — it stringifies whatever came back:

    flags = {str(p) for p in payload.get("low_confidence") or []}

So the model can return `transactions.7.quantity` for an invoice with three rows, or
`customer.name`, which is not in the grammar at all. Either one silently breaks the
review screen's ability to put an amber marker on the field, because there is no
field at that path to mark — the "3 fields need a look" counter says three and the
user finds two. That is a real defect with no other detector, and it is what this
metric measures.
"""

from __future__ import annotations

from evals.metrics.base import DeterministicMetric, Result, ratio
from evals.schema import is_valid_path

_LINE_FIELDS = ("description", "quantity", "unit_price")


def unresolvable_paths(payload: dict) -> list[tuple[str, str]]:
    """`low_confidence` entries that point at nothing. Returns (path, why)."""
    rows = payload.get("transactions") or []
    problems: list[tuple[str, str]] = []

    for path in payload.get("low_confidence") or []:
        path = str(path)
        if not is_valid_path(path):
            problems.append(
                (path, "not one of the paths the prompt defines")
            )
            continue
        if path.startswith("transactions."):
            _, index, field = path.split(".", 2)
            position = int(index)
            if position >= len(rows):
                problems.append(
                    (
                        path,
                        f"row {position} does not exist — only {len(rows)} line "
                        "item(s) came back",
                    )
                )
            elif field not in _LINE_FIELDS:
                problems.append((path, f"line items have no {field!r} field"))

    return problems


class LowConfidencePathsResolve(DeterministicMetric):
    """Every flagged path must name a field that exists in the payload."""

    name = "low_confidence paths resolve"

    def evaluate(self, case) -> Result:
        payload = case.payload
        flags = [str(p) for p in payload.get("low_confidence") or []]
        problems = unresolvable_paths(payload)

        score = ratio(len(flags) - len(problems), len(flags))

        if not flags:
            return Result(
                score=score, reason="nothing was flagged, so no paths to resolve"
            )
        if not problems:
            return Result(
                score=score,
                reason=f"all {len(flags)} flagged path(s) name a real field",
            )

        return Result(
            score=score,
            reason=(
                f"{len(problems)} of {len(flags)} flagged path(s) point at nothing, "
                "so the review screen counts a field that needs a look and then "
                "cannot mark it: "
                + "; ".join(f"{path!r} ({why})" for path, why in problems)
            ),
            detail={"unresolvable": problems, "flags": flags},
        )
