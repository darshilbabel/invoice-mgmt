# AGENTS.md

Rules for any AI coding tool working in this repository — model- and tool-agnostic. Claude Code
additionally reads `CLAUDE.md`, which points here and adds Claude-specific detail.

## What this is

Invoice management system. Django + DRF + PostgreSQL backend, React + TypeScript frontend. Built
as the running project for a training programme and carried forward across sessions, so
conventions matter more than speed. Docs live in `docs/`:

- `docs/architecture.md` — services, API surface, data flow, repo layout
- `docs/domain.md` — the models and the computed-total rule
- `docs/conventions.md` — naming, errors, migrations, permissions, money handling
- `docs/design-tokens.md` — the frontend design system and its hard rules
- `docs/specs/` — one file per in-flight feature ticket

`prd.md` at the repo root is the originating brief. `docs/architecture.md` supersedes it wherever
they differ, and records every such deviation with the reasoning.

## Standing rules

- **Never hand-edit anything under `migrations/`.** Always generate via
  `python manage.py makemigrations`.
- **No new library without asking first** — pip or npm. Approved lists are in
  `docs/conventions.md`.
- **Nothing beyond what a ticket actually asks for.** This app is deliberately small.
- **Flag uncertainty as a question** rather than picking an answer and moving on.
- **Plan before code.** For anything non-trivial: a numbered implementation plan in dependency
  order, one line per item, each naming its own verification step — approved before writing code.
- **There is no automated test suite**, by deliberate choice (`docs/architecture.md`'s decision
  log). Verification is `manage.py check`, `makemigrations --check --dry-run`, the Django shell,
  and `curl`/browser checks against a running server. State this explicitly in any plan.

## Commands

```bash
# backend — from repo root; venv lives at the repo root
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
python manage.py check
python manage.py makemigrations
python manage.py migrate
python manage.py runserver          # :8000

# frontend
cd frontend
npm install
npm run dev                         # :5173
npm run build                       # tsc -b && vite build — the real type-check gate
npx tsc --noEmit                    # faster, but weaker than `build`
```

`manage.py check` and `manage.py dbshell` do **not** prove Django can use the database — `check`
never opens a connection, and `dbshell` execs `psql` directly, bypassing Django's engine. To
actually exercise the connection:

```bash
python -c "import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); \
django.setup(); from django.db import connection; connection.ensure_connection(); print(connection.pg_version)"
```

## The one rule that matters most

**Invoice totals are computed from the invoice's transactions, never stored as a flat field.**
See `docs/domain.md` for the implementation and the rounding rule. There is no test guarding
this — verify it by hand whenever invoices or line items change.
