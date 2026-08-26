"""Runs the system under test, and caches what it said.

The system under test is `billing.extraction.extract_invoice_fields` — bytes in,
dict out, no ORM, no database. This module is the only place in the suite that calls
it, and the only place that spends money on OpenAI.

## The cache key is the interesting part

Every fixture costs one OpenAI call per run. Iterating on a metric would otherwise
re-bill the entire fixture set on every edit, so results are cached. What they are
keyed on is not a performance detail — it is the difference between a cache and a
lie:

    sha256(pdf bytes) | OPENAI_MODEL | sha256(PROMPT + canonical SCHEMA)

`docs/specs/2026-08-ocr-ingest.md` names the three things that silently degrade
extraction: *"Re-do this by hand whenever the prompt, the model or the schema
changes — none of those failures are loud."* A key of `(pdf, model)` alone would
serve a stale answer after a prompt edit — reporting "no regression" for the exact
change most likely to have caused one. So all three are in the key, and all three
are recorded in the envelope beside the payload, so a cached entry can say for
itself what produced it.

`EVAL_REFRESH=1` bypasses the cache and re-bills deliberately.

An environment variable rather than a pytest flag because `deepeval test run` wraps
pytest in its own argument parser and does not forward custom `pytest_addoption`
flags — an env var is the one contract that works under both runners. Note this is a
different thing from deepeval's own `-c`, which caches *metric* results rather than
the extraction call; the two compose.

## Errors are cached too

An `ExtractionError` is a legitimate outcome — some fixtures exist precisely to
produce one (`expect_error` in the golden). Caching only successes would re-bill
those on every run for no reason, and would make a rejection fixture slower than a
real invoice.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from billing import extraction

CACHE_DIR = Path(__file__).resolve().parent / ".cache"

#: Set to "1" to ignore cached results and call OpenAI again.
REFRESH_ENV = "EVAL_REFRESH"


def refresh_requested() -> bool:
    return os.environ.get(REFRESH_ENV, "").strip() not in ("", "0", "false", "False")


def contract_fingerprint() -> str:
    """A hash of the prompt and schema the extractor is currently asking with.

    Canonical JSON (`sort_keys`) so that reordering a schema key — which changes
    nothing about what is asked — does not invalidate every cached result.
    """
    material = extraction.PROMPT + json.dumps(extraction.SCHEMA, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def cache_key(pdf_bytes: bytes) -> str:
    parts = [
        hashlib.sha256(pdf_bytes).hexdigest(),
        settings.OPENAI_MODEL,
        contract_fingerprint(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


@dataclass
class Outcome:
    """What the extractor did with one PDF.

    Exactly one of `payload` / `error_reason` is set. Callers branch on `ok`.
    """

    ok: bool
    payload: dict | None
    error_reason: str | None
    error_message: str | None
    #: True when this came from disk rather than from OpenAI.
    cached: bool
    #: Seconds the original call took. Kept because the blocking-extract latency is
    #: a tracked risk in docs/qa-strategy.md section 5, and this is the only place
    #: it gets measured at all.
    duration_seconds: float

    @property
    def transactions(self) -> list[dict]:
        return list((self.payload or {}).get("transactions") or [])


def _envelope_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _read_cache(key: str) -> Outcome | None:
    path = _envelope_path(key)
    if not path.exists():
        return None
    try:
        envelope = json.loads(path.read_text())
    except (ValueError, OSError):
        return None  # a corrupt entry is just a miss; it gets rewritten
    return Outcome(
        ok=envelope["ok"],
        payload=envelope.get("payload"),
        error_reason=envelope.get("error_reason"),
        error_message=envelope.get("error_message"),
        cached=True,
        duration_seconds=envelope.get("duration_seconds", 0.0),
    )


def _write_cache(key: str, outcome: Outcome, pdf_path: Path) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    envelope = {
        # Self-describing on purpose: opening a cache file should tell you what
        # produced it without having to reconstruct the key.
        "_produced_by": {
            "source_pdf": pdf_path.name,
            "openai_model": settings.OPENAI_MODEL,
            "contract_fingerprint": contract_fingerprint(),
        },
        "ok": outcome.ok,
        "payload": outcome.payload,
        "error_reason": outcome.error_reason,
        "error_message": outcome.error_message,
        "duration_seconds": outcome.duration_seconds,
    }
    _envelope_path(key).write_text(json.dumps(envelope, indent=2, sort_keys=True))


def run_extraction(pdf_path: str | Path, refresh: bool | None = None) -> Outcome:
    """Extract one PDF, using the cache unless told not to."""
    pdf_path = Path(pdf_path)
    pdf_bytes = pdf_path.read_bytes()
    key = cache_key(pdf_bytes)

    if refresh is None:
        refresh = refresh_requested()

    if not refresh:
        cached = _read_cache(key)
        if cached is not None:
            return cached

    started = time.monotonic()
    try:
        payload = extraction.extract_invoice_fields(pdf_bytes, pdf_path.name)
        outcome = Outcome(
            ok=True,
            payload=payload,
            error_reason=None,
            error_message=None,
            cached=False,
            duration_seconds=time.monotonic() - started,
        )
    except extraction.ExtractionError as exc:
        outcome = Outcome(
            ok=False,
            payload=None,
            error_reason=exc.reason,
            error_message=exc.message,
            cached=False,
            duration_seconds=time.monotonic() - started,
        )

    _write_cache(key, outcome, pdf_path)
    return outcome


def _main(argv: list[str]) -> int:
    """`python -m evals.runner [--key-only] <pdf>` — for checking the key by hand."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--key-only",
        action="store_true",
        help="print the cache key and exit, without calling OpenAI",
    )
    parser.add_argument("--refresh", action="store_true", help="ignore any cached result")
    args = parser.parse_args(argv)

    pdf_bytes = args.pdf.read_bytes()
    print(f"model       {settings.OPENAI_MODEL}")
    print(f"contract    {contract_fingerprint()[:16]}...")
    print(f"cache key   {cache_key(pdf_bytes)}")
    if args.key_only:
        return 0

    outcome = run_extraction(args.pdf, refresh=args.refresh)
    print(f"cached      {outcome.cached}")
    print(f"duration    {outcome.duration_seconds:.1f}s")
    if not outcome.ok:
        print(f"ERROR       {outcome.error_reason}: {outcome.error_message}")
        return 1
    print(json.dumps(outcome.payload, indent=2))
    return 0


if __name__ == "__main__":
    import sys

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    raise SystemExit(_main(sys.argv[1:]))
