"""Django-then-deepeval bootstrap, for entry points that are not pytest.

`conftest.py` does exactly this and explains why the order is load-bearing: Django's
settings module is what puts ANTHROPIC_API_KEY into `os.environ` (via django-environ
reading backend's dotenv), and deepeval snapshots its settings at import time — so
importing deepeval before `django.setup()` gives it a half-built environment.

This module exists rather than being imported *from* `conftest.py` because pytest
imports a conftest before anything else in the package, so conftest has to be
self-contained. Anything with a `__main__` — `evals.report` — imports this first
instead. Importing both is harmless: `django.setup()` is idempotent and the rest is
`setdefault`/`pop`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

# Set before deepeval is imported anywhere. See conftest.py for the full reasoning:
# DEEPEVAL_MODEL_THINKING is *popped* rather than left unset because deepeval reads
# it from a dotenv it autoloads from the working directory, and claude-sonnet-5
# rejects the `budget_tokens` field that flag makes deepeval send.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
os.environ.pop("DEEPEVAL_MODEL_THINKING", None)
