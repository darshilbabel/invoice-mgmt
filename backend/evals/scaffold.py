"""Turn a PDF into a draft golden for a human to correct.

    python -m evals.scaffold ~/Downloads/acme-march.pdf

Copies the PDF into `evals/fixtures/`, runs extraction once, and writes
`<name>.expected.json` pre-filled with what came back — as a **starting point to
correct**, never as an answer key.

## What it deliberately refuses to fill in

`issuer` is written as explicit nulls and `ambiguous` as an empty map, even though
the extraction has opinions about both. This is the point of the whole module.

A golden scaffolded from the model's own output and never checked scores a perfect
1.0 while measuring nothing at all. `_verified: false` is the blunt guard against
that. But there is a sharper failure it would not catch: if the model confused the
two parties — returned the letterhead as the customer, the highest-consequence
failure this suite exists to detect — and the scaffold had pre-filled `issuer` from
that same output, the golden would encode the confusion and `metrics/direction.py`
would pass forever, on every future run, silently.

So the one field that proves the model got the parties right is the one field the
model is not allowed to supply. `dataset.py` refuses a fixture whose `issuer.name`
is still null, for the same reason it refuses `_verified: false`.

`ambiguous` is blank for a related reason: it drives calibration *recall*, and
seeding it from what the model chose to flag would score the model against its own
opinion of what is hard to read.

## What it does fill in

`rounding_divergent`, computed from the extracted line items — whether
round-each-then-sum and sum-then-round disagree on this invoice. It is a fact about
arithmetic, not a judgement, so there is nothing for a human to verify. It drives
the coverage warning in `dataset.py`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from evals.money import round_then_sum, sum_then_round
from evals.runner import run_extraction

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

DRAFT_NOTE = (
    "DRAFT — not yet verified. Read the PDF and correct every field below, then "
    "fill in `issuer` (all three fields) and `ambiguous`, then set `_verified` to "
    "true. Values here came from the extractor and are exactly what this suite is "
    "supposed to be checking, so trusting them makes the fixture measure nothing."
)


def draft_from_outcome(outcome, pdf_name: str) -> dict:
    """Build the draft golden dict for one extraction outcome."""
    if not outcome.ok:
        # A rejection is a legitimate fixture. Record what was raised so the
        # reviewer can confirm it is the *right* rejection for this document.
        return {
            "_verified": False,
            "_note": DRAFT_NOTE,
            "source_pdf": pdf_name,
            "page_count": 0,
            "issuer": {"name": None, "email": None, "address": None},
            "bill_to": {"name": None, "email": None, "address": None},
            "customer_absent": True,
            "expect_error": {"reason": outcome.error_reason},
        }

    payload = outcome.payload or {}
    guess = payload.get("customer_guess") or {}
    lines = [
        {
            "description": row.get("description", ""),
            "quantity": row.get("quantity", "0.00"),
            "unit_price": row.get("unit_price", "0.00"),
        }
        for row in payload.get("transactions") or []
    ]

    return {
        "_verified": False,
        "_note": DRAFT_NOTE,
        "source_pdf": pdf_name,
        "page_count": payload.get("page_count") or 0,
        # Left blank on purpose — see the module docstring.
        "issuer": {"name": None, "email": None, "address": None},
        "bill_to": {
            "name": guess.get("name") or None,
            "email": guess.get("email") or None,
            "address": guess.get("billing_address") or None,
        },
        "customer_absent": not guess,
        "source_invoice_number": payload.get("source_invoice_number"),
        "issue_date": payload.get("issue_date"),
        "due_date": payload.get("due_date"),
        "printed_total": payload.get("printed_total"),
        "printed_total_absent": payload.get("printed_total") is None,
        "line_items": lines,
        # Seeded empty: the reviewer adds the invoice's own summary rows here
        # ("Subtotal", "GST 18%", "Grand total") as they appear on the page.
        "forbidden_descriptions": [],
        # Left blank on purpose — see the module docstring.
        "ambiguous": {},
        "notes_source_text": "",
        "rounding_divergent": round_then_sum(lines) != sum_then_round(lines),
        "expect_error": None,
    }


def scaffold(pdf: str | Path, refresh: bool = False) -> Path:
    """Copy `pdf` into fixtures/ and write its draft golden. Returns the JSON path."""
    source = Path(pdf).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"No such file: {source}")

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    target = FIXTURES_DIR / source.name
    if source != target:
        shutil.copy2(source, target)

    golden_path = target.with_suffix("").with_suffix(".expected.json")
    if golden_path.exists():
        raise SystemExit(
            f"{golden_path.name} already exists — refusing to overwrite a golden "
            "someone may have verified by hand. Delete it first if that is really "
            "what you want."
        )

    outcome = run_extraction(target, refresh=refresh)
    draft = draft_from_outcome(outcome, target.name)
    golden_path.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n")
    return golden_path


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", nargs="+", type=Path)
    parser.add_argument(
        "--refresh", action="store_true", help="re-extract even if cached"
    )
    args = parser.parse_args(argv)

    for pdf in args.pdf:
        path = scaffold(pdf, refresh=args.refresh)
        print(f"wrote {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")
    print()
    print("Next, for each one: read the PDF, correct every field, fill in `issuer`")
    print("and `ambiguous`, then set `_verified` to true. Until then the suite will")
    print("refuse to load it — deliberately.")
    return 0


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    raise SystemExit(_main(sys.argv[1:]))
