"""Bootstraps Django, then deepeval — in that order, which is load-bearing.

`django.setup()` must run before anything imports deepeval. Two reasons:

1. `config/settings.py` calls `environ.Env.read_env(BASE_DIR / <dotenv>)`, and
   django-environ writes what it reads into `os.environ`. That is what puts
   ANTHROPIC_API_KEY in the process — this file does not load it itself, and
   `settings.py` deliberately does not know the key exists (adding it there would
   make the application depend on an eval-only secret; see backend/CLAUDE.md).
2. deepeval snapshots its settings at import time. Import it before the environment
   is populated and it reads a half-built one.

So: stdlib, Django bootstrap, environment fixes, and only then anything else.
"""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

# --- deepeval environment, set before deepeval is imported anywhere -----------

# No usage pings. This is a local measurement harness; nothing about it needs to
# leave the machine except the two model calls it makes on purpose.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")

# Popped, not merely "left unset". deepeval also reads this from a dotenv file it
# autoloads from the working directory, so a value can arrive without anyone here
# setting one. With it set, deepeval sends
# `thinking={"type": "enabled", "budget_tokens": N}` to any model registered as
# supports_thinking=True — and claude-sonnet-5 removed `budget_tokens`, so that
# request is a 400. Unset, deepeval sends {"type": "disabled"}, which is accepted.
os.environ.pop("DEEPEVAL_MODEL_THINKING", None)

import pytest  # noqa: E402


def pytest_configure(config):
    """Register markers, and fail early and legibly if the judge has no key.

    Checked here rather than inside judge.py so the message arrives once, at
    startup, instead of once per metric partway through a billable run.
    """
    config.addinivalue_line(
        "markers", "billable: makes a real OpenAI or Anthropic call"
    )
    config.addinivalue_line(
        "markers", "judged: uses the claude-sonnet-5 judge (extra cost)"
    )

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise pytest.UsageError(
            "ANTHROPIC_API_KEY is not set. The eval judge is claude-sonnet-5.\n"
            "It is read out of backend's dotenv file by config/settings.py, so this "
            "usually means the key is missing from that file rather than that "
            "anything here is misconfigured. See evals/README.md."
        )
