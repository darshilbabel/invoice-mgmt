"""Records which stages of `billing/extraction.py` actually ran, for tool correctness.

## Why this module exists at all

`ToolCorrectnessMetric` compares `test_case.tools_called` against
`test_case.expected_tools`. Nothing in this project is an agent, so there is no
model-chosen tool call to compare — the extractor makes exactly one model call and
the pipeline around it is straight-line Python.

What there *is* worth checking is that the pipeline **took the whole path**. A
degraded scan has two shapes of failure that look identical in the payload metrics:

- it short-circuits into `ExtractionError` before the model is ever called (an empty
  or unreadable upload), and
- it reaches the model, gets `has_content: false` back, and rejects after the call.

The first is a rejection the user can act on; the second means the model looked at
the page and said there was no invoice on it. `metrics/scalars.py` cannot tell them
apart because both produce no payload at all. The stage trace can.

So the "tools" here are the four stages of `extract_invoice_fields`, plus the
rejection stage. It is a real record of a real run, not a label invented afterwards.

## How the trace is obtained, and why it is not reconstructed

The stages are recorded by wrapping the module-level names `extraction.py` actually
calls — `base64.b64encode`, `openai.OpenAI(...).responses.create`, `json.loads` and
`_normalise` — for the duration of one call, then putting them back. Nothing in
`billing/extraction.py` is edited, and nothing about the trace is inferred from the
payload: a stage appears in the trace because it ran.

Reconstructing it from the payload instead ("there are line items, so `_normalise`
must have run") would make the metric agree with itself by construction, which is
the same failure `dataset.py` refuses `_verified: false` fixtures for.

## The cache, and the cost

A trace needs a live call — a cached extraction has no stages to observe. So this
module keeps its own cache under `.cache/traces/`, keyed **identically** to
`runner.py`'s (pdf bytes | model | prompt+schema), and on a cold trace it writes
`runner.py`'s envelope too. One OpenAI call produces both, so tracing a fixture the
suite has not seen costs one call, not two, and tracing one it has costs one call
once and nothing after.
"""

from __future__ import annotations

import base64 as _real_base64
import json as _real_json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import openai as _real_openai
from django.conf import settings

from billing import extraction
from evals.runner import CACHE_DIR, Outcome, _write_cache, cache_key, contract_fingerprint

TRACE_CACHE_DIR = CACHE_DIR / "traces"

# --- the stage vocabulary ----------------------------------------------------
# Named for what the code does, not for what a model chose, because no model chose
# anything here. Order is the dependency order of extract_invoice_fields().

ENCODE_PDF = "encode_pdf_base64"
OPENAI_CALL = "openai_responses_create"
PARSE_OUTPUT = "parse_structured_output"
NORMALISE = "normalise_payload"
REJECT = "raise_extraction_error"

#: What a readable invoice must drive: all four stages, no rejection.
HAPPY_PATH = (ENCODE_PDF, OPENAI_CALL, PARSE_OUTPUT, NORMALISE)

#: What a page the model reports as having no invoice on it must drive: the model
#: is still called, and the rejection happens after it rather than instead of it.
POST_MODEL_REJECTION = (ENCODE_PDF, OPENAI_CALL, PARSE_OUTPUT, REJECT)

#: Every stage that exists. `ToolCorrectnessMetric` needs this as `available_tools`
#: to score tool *selection* at all — without it the metric says so and grades only
#: the ordering half.
ALL_STAGES = (ENCODE_PDF, OPENAI_CALL, PARSE_OUTPUT, NORMALISE, REJECT)


@dataclass
class Stage:
    """One recorded stage: what ran, and the one fact worth keeping about it."""

    name: str
    detail: dict = field(default_factory=dict)


@dataclass
class Trace:
    """The stages one extraction actually ran, in the order they ran."""

    stages: list[Stage]
    outcome: Outcome
    cached: bool

    @property
    def names(self) -> list[str]:
        return [stage.name for stage in self.stages]


class _Recorder:
    def __init__(self) -> None:
        self.stages: list[Stage] = []

    def record(self, name: str, **detail) -> None:
        self.stages.append(Stage(name=name, detail=detail))


class _ModuleProxy:
    """Forwards every attribute to the real module except the ones we wrap.

    Needed because `extraction.py` reaches for `openai.APITimeoutError` and
    `openai.BadRequestError` in its `except` clauses. A bare mock in that slot turns
    a timeout into an `AttributeError` inside an exception handler, which is a
    genuinely horrible thing to debug.
    """

    def __init__(self, real, overrides: dict):
        self._real = real
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._real, name)


@contextmanager
def _instrumented(recorder: _Recorder):
    """Wrap the four names `extract_invoice_fields` calls, then put them back."""

    def b64encode(data, *args, **kwargs):
        recorder.record(ENCODE_PDF, pdf_bytes=len(data))
        return _real_base64.b64encode(data, *args, **kwargs)

    def loads(text, *args, **kwargs):
        recorder.record(PARSE_OUTPUT, characters=len(text or ""))
        return _real_json.loads(text, *args, **kwargs)

    real_normalise = extraction._normalise

    def normalise(payload, *args, **kwargs):
        recorder.record(
            NORMALISE,
            rows=len(payload.get("transactions") or []),
            model_flags=len(payload.get("low_confidence") or []),
        )
        return real_normalise(payload, *args, **kwargs)

    class _ResponsesProxy:
        def __init__(self, real_responses):
            self._real = real_responses

        def create(self, *args, **kwargs):
            started = time.monotonic()
            response = self._real.create(*args, **kwargs)
            recorder.record(
                OPENAI_CALL,
                model=kwargs.get("model"),
                # The response format is the half of the contract that decides
                # whether anything downstream can parse the answer at all.
                response_format=(kwargs.get("text") or {}).get("format", {}).get("type"),
                seconds=round(time.monotonic() - started, 2),
            )
            return response

        def __getattr__(self, name):
            return getattr(self._real, name)

    class _ClientProxy:
        def __init__(self, real_client):
            self._real = real_client
            self.responses = _ResponsesProxy(real_client.responses)

        def __getattr__(self, name):
            return getattr(self._real, name)

    def OpenAI(*args, **kwargs):  # noqa: N802 - mirrors the real constructor's name
        return _ClientProxy(_real_openai.OpenAI(*args, **kwargs))

    originals = {
        "base64": extraction.base64,
        "json": extraction.json,
        "openai": extraction.openai,
        "_normalise": extraction._normalise,
    }
    extraction.base64 = _ModuleProxy(_real_base64, {"b64encode": b64encode})
    extraction.json = _ModuleProxy(_real_json, {"loads": loads})
    extraction.openai = _ModuleProxy(_real_openai, {"OpenAI": OpenAI})
    extraction._normalise = normalise
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(extraction, name, value)


def _trace_path(key: str) -> Path:
    return TRACE_CACHE_DIR / f"{key}.json"


def _read_trace(key: str) -> Trace | None:
    path = _trace_path(key)
    if not path.exists():
        return None
    try:
        envelope = _real_json.loads(path.read_text())
    except (ValueError, OSError):
        return None
    return Trace(
        stages=[Stage(name=s["name"], detail=s.get("detail", {})) for s in envelope["stages"]],
        outcome=Outcome(
            ok=envelope["ok"],
            payload=envelope.get("payload"),
            error_reason=envelope.get("error_reason"),
            error_message=envelope.get("error_message"),
            cached=True,
            duration_seconds=envelope.get("duration_seconds", 0.0),
        ),
        cached=True,
    )


def _write_trace(key: str, trace: Trace, pdf_path: Path) -> None:
    TRACE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _trace_path(key).write_text(
        _real_json.dumps(
            {
                "_produced_by": {
                    "source_pdf": pdf_path.name,
                    "openai_model": settings.OPENAI_MODEL,
                    "contract_fingerprint": contract_fingerprint(),
                },
                "stages": [{"name": s.name, "detail": s.detail} for s in trace.stages],
                "ok": trace.outcome.ok,
                "payload": trace.outcome.payload,
                "error_reason": trace.outcome.error_reason,
                "error_message": trace.outcome.error_message,
                "duration_seconds": trace.outcome.duration_seconds,
            },
            indent=2,
            sort_keys=True,
        )
    )


def traced_extraction(pdf_path: str | Path, refresh: bool = False) -> Trace:
    """Extract one PDF, recording which stages ran. Cached like `run_extraction`."""
    pdf_path = Path(pdf_path)
    pdf_bytes = pdf_path.read_bytes()
    key = cache_key(pdf_bytes)

    if not refresh:
        cached = _read_trace(key)
        if cached is not None:
            return cached

    recorder = _Recorder()
    started = time.monotonic()
    with _instrumented(recorder):
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
            recorder.record(REJECT, reason=exc.reason)
            outcome = Outcome(
                ok=False,
                payload=None,
                error_reason=exc.reason,
                error_message=exc.message,
                cached=False,
                duration_seconds=time.monotonic() - started,
            )

    trace = Trace(stages=recorder.stages, outcome=outcome, cached=False)
    _write_trace(key, trace, pdf_path)
    # One call, both caches. Written second so a failure here cannot leave a trace
    # on disk claiming an extraction the payload cache does not have.
    _write_cache(key, outcome, pdf_path)
    return trace


def expected_stages(golden) -> tuple[str, ...]:
    """What this fixture's golden says the pipeline should have run.

    A golden with `expect_error` set for the `no_text` reason expects the model to
    be called and *then* to report an empty page — that is the whole point of
    sending a scan to a vision model rather than to a text extractor. Any other
    golden expects the full happy path.
    """
    expected_error = getattr(golden, "expect_error", None)
    if expected_error is not None and expected_error.reason == extraction.NO_TEXT:
        return POST_MODEL_REJECTION
    return HAPPY_PATH
