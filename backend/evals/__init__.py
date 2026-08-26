"""Extraction evals — a measurement harness, not a Django app.

**Never add this package to `INSTALLED_APPS`.** It has no models, no `apps.py`, no
migrations, and nothing in the application imports it. It sits beside `accounts/`
and `billing/` only so `DJANGO_SETTINGS_MODULE=config.settings` resolves without
`sys.path` surgery.

What it is: a scored, repeatable eval over `billing.extraction.extract_invoice_fields`
— the one part of this codebase whose output is not deterministic and therefore
cannot be unit-tested. `docs/qa-strategy.md` section 4 lists the OpenAI adapter as
"billable and nondeterministic; rejection paths only". This is the other half.

Its dependencies (`deepeval`, `anthropic`) are pinned in `evals/requirements.txt`,
deliberately NOT in `backend/requirements.txt`: the application must keep running
for someone who has never installed them. See `docs/conventions.md` § Dependencies.

`manage.py check` does not import this package. Verification here is
`pytest evals/ --collect-only`, not `check`. Start at `evals/README.md`.
"""
