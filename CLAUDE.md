# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Invoice management system, greenfield. Django + DRF + PostgreSQL backend, React + TypeScript frontend.
Built as the running project for a four-session training programme — it is treated as a
real repo and carried forward between sessions, so conventions matter more than speed.

Scope is deliberately small: two or three pages of application.

**Read `architecture.md` before starting any work.** It is the settled design contract — exact
model fields, the API surface and permission matrix, the computed-total rule, admin
requirements, and the dependency-ordered implementation plan. Decisions there were made
deliberately; do not re-decide them mid-build. If something in it needs to change, change the
document too.

`prd.md` holds the originating brief. `architecture.md` supersedes it wherever the two differ,
and its section 8 records every such deviation with the reasoning.

## Current state

Design is settled; no application code exists yet. The repo holds `prd.md`, `architecture.md`,
this file, and a bare virtualenv at `.venv/` (Python 3.14.3, `pip` only — Django is not yet
installed). Implementation starts at step 1 of `architecture.md` section 9.

Activate the venv with `source .venv/bin/activate` before any Python work.

## Commands

Backend commands run from `backend/`; the venv lives at the repo root.

```bash
source .venv/bin/activate          # from the repo root
pip install -r backend/requirements.txt

cd backend
python manage.py check             # after every settings/model change
python manage.py makemigrations    # never hand-edit the output
python manage.py migrate
python manage.py runserver         # :8000
```

There is no test suite by design — see `architecture.md` section 8. Verification is
`manage.py check`, `makemigrations --check --dry-run`, the shell, and curl.

**`manage.py check` and `manage.py dbshell` do NOT prove Django can use the database.** `check`
never opens a connection, and `dbshell` execs the `psql` binary directly, bypassing Django's
engine. A version or driver incompatibility passes both and then fails on `runserver`. To
actually exercise the connection:

```bash
python -c "import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); \
django.setup(); from django.db import connection; connection.ensure_connection(); print(connection.pg_version)"
```

Frontend commands land at step 13.

## Standing rules

These come from the project brief and apply to every session:

- **Never hand-edit anything under `migrations/`.** Always generate migrations via
  `python manage.py makemigrations`.
- **No new libraries without asking first.** This includes both pip and npm dependencies. The
  already-approved lists are in `architecture.md` section 1 — anything outside them needs a new
  conversation.
- **Nothing beyond CRUD, login, and the dashboard.** Do not add features that weren't asked for.
- **Flag uncertainty as a question** rather than picking an answer and moving on.
- **Plan before code.** Deliver a numbered implementation plan in dependency order, one line per
  item, specific enough to be rejected without reading further — and wait for approval before writing code.
- **Every plan item names its verification step** — what will be run to prove it works. E.g.
  "`Transaction` model — FK to `Invoice` (on_delete=CASCADE), quantity, unit_price; verify:
  `python manage.py check` plus a shell check that the FK is required".

## The rule that matters most

**Invoice totals are computed from the invoice's transactions, never stored as a flat field.**

Concretely: a `total` property on `Invoice` sums `line_total` across `self.transactions.all()`,
and list querysets call `.prefetch_related("transactions")` so N invoices cost 2 queries. One
code path serves the API, the admin and the shell — do not add a second SQL implementation that
could drift from it. See `architecture.md` section 4, including why `?ordering=total` is
deliberately unavailable.

There is **no test suite** (a deliberate call, recorded in `architecture.md` section 8), so
nothing automated guards this rule. Verify it by hand whenever you touch invoices or line items.
