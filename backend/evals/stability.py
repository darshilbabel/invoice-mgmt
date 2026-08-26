"""Runs one PDF through the extractor N times, because once is not a measurement.

## The gap this closes

`runner.py` extracts each fixture once and caches the result. Every metric in this
suite then scores that single sample. For a legible invoice that is fine — the
extraction is near-deterministic and the cache is what makes the suite affordable.

For a document at the edge of readability it is not fine, and
`113_augraphy_scan_lines.pdf` is the proof. Sampled twelve times it **refused seven
times and fabricated an invoice five times** — a different invented customer and a
different invented total on each. Whichever answer happened to land in the cache
became the fixture's verdict, and the fixture scored a clean pass on the runs where
it refused.

That is the same failure the judge had, one layer down and with far worse
consequences: `evals/report.py` samples every judged metric five times *because*
`claude-sonnet-5` cannot be pinned to greedy decoding, and then scored the
extractor — which cannot be pinned either — exactly once.

## What it measures, and what it deliberately does not

A refusal rate, and a fingerprint of each fabrication. **Not** a pass/fail on the
content of any single fabricated payload: they disagree with each other, so there is
no golden to compare against and nothing stable to score. The fingerprints exist so
a reader can see *what kind* of thing gets invented, which is the part that tells
you how bad the failure is. An invented `Customer` row is permanent
(`on_delete=PROTECT`); an invented total is a number a human approves on the review
screen believing it was read off the page.

## Cost, and why the cache tops up rather than replacing

Every sample is a real, billable call — `runner.py`'s cache cannot help, since the
whole point is to see the variation the cache hides. So samples accumulate: ask for
eight when six are cached and it makes two calls, not eight. `refresh=True`
discards and re-collects, which is what to do after changing the prompt or model.

The cache key is `runner.cache_key`'s — pdf bytes, model, prompt and schema
together — so a prompt edit invalidates the sample set exactly as it invalidates
the extraction. That matters more here than anywhere else in the suite: "does it
still hallucinate" is the single question a prompt change most needs re-answered.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from django.conf import settings

from billing import extraction
from evals.runner import CACHE_DIR, cache_key, contract_fingerprint

STABILITY_CACHE_DIR = CACHE_DIR / "stability"


@dataclass
class Sample:
    """One live extraction of one PDF.

    `fingerprint` is deliberately a handful of scalars rather than the whole
    payload: the point is to compare samples with each other at a glance, and two
    fabrications differ in the fields named here.
    """

    ok: bool
    error_reason: str | None = None
    fingerprint: dict = field(default_factory=dict)

    @property
    def refused(self) -> bool:
        return not self.ok


def _fingerprint(payload: dict) -> dict:
    rows = payload.get("transactions") or []
    customer = payload.get("customer_guess") or {}
    return {
        "customer": customer.get("name") or None,
        "invoice_number": payload.get("source_invoice_number"),
        "issue_date": payload.get("issue_date"),
        "due_date": payload.get("due_date"),
        "printed_total": payload.get("printed_total"),
        "rows": [
            {
                "description": row.get("description"),
                "quantity": row.get("quantity"),
                "unit_price": row.get("unit_price"),
            }
            for row in rows
        ],
        # The field that decides whether a fabrication reaches the reviewer wearing
        # an amber marker or wearing nothing at all.
        "low_confidence": payload.get("low_confidence") or [],
    }


@dataclass
class Samples:
    """Every sample collected for one PDF, and the summary a metric scores."""

    pdf_name: str
    samples: list[Sample]

    @property
    def count(self) -> int:
        return len(self.samples)

    @property
    def refusals(self) -> int:
        return sum(1 for sample in self.samples if sample.refused)

    @property
    def extractions(self) -> list[Sample]:
        return [sample for sample in self.samples if sample.ok]

    @property
    def refusal_rate(self) -> float:
        return self.refusals / self.count if self.count else 0.0

    def fabricated_customers(self) -> list[str]:
        names = [s.fingerprint.get("customer") for s in self.extractions]
        return sorted({name for name in names if name})

    def fabricated_totals(self) -> list[str]:
        totals = [s.fingerprint.get("printed_total") for s in self.extractions]
        return sorted({total for total in totals if total})

    def unflagged_fabrications(self) -> list[Sample]:
        """Extractions carrying a customer or a total with no low_confidence flag on it.

        The worst shape this failure takes. A fabrication the model *flags* arrives
        at the review screen wearing the amber marker the design system reserves for
        exactly this; an unflagged one arrives looking like it was read off the page.
        """
        worst = []
        for sample in self.extractions:
            flags = set(sample.fingerprint.get("low_confidence") or [])
            invented_customer = bool(sample.fingerprint.get("customer"))
            total = sample.fingerprint.get("printed_total")
            if (invented_customer or total) and "printed_total" not in flags:
                worst.append(sample)
        return worst


def _path(key: str) -> Path:
    return STABILITY_CACHE_DIR / f"{key}.json"


def _read(key: str) -> list[Sample]:
    path = _path(key)
    if not path.exists():
        return []
    try:
        envelope = json.loads(path.read_text())
    except (ValueError, OSError):
        return []
    return [Sample(**row) for row in envelope.get("samples", [])]


def _write(key: str, pdf_path: Path, samples: list[Sample]) -> None:
    STABILITY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _path(key).write_text(
        json.dumps(
            {
                "_produced_by": {
                    "source_pdf": pdf_path.name,
                    "openai_model": settings.OPENAI_MODEL,
                    "contract_fingerprint": contract_fingerprint(),
                },
                "samples": [asdict(sample) for sample in samples],
            },
            indent=2,
            sort_keys=True,
        )
    )


def sample_extractions(
    pdf_path: str | Path, n: int = 8, refresh: bool = False
) -> Samples:
    """Extract one PDF `n` times, topping up the cache rather than replacing it."""
    pdf_path = Path(pdf_path)
    pdf_bytes = pdf_path.read_bytes()
    key = cache_key(pdf_bytes)

    collected = [] if refresh else _read(key)

    while len(collected) < n:
        try:
            payload = extraction.extract_invoice_fields(pdf_bytes, pdf_path.name)
            collected.append(Sample(ok=True, fingerprint=_fingerprint(payload)))
        except extraction.ExtractionError as exc:
            collected.append(Sample(ok=False, error_reason=exc.reason))

    _write(key, pdf_path, collected)
    return Samples(pdf_name=pdf_path.name, samples=collected[:n])
