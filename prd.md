**Context:** Greenfield invoice management system, built from an empty repo as the
running project for a four-session training programme. Django + PostgreSQL on the
back, React on the front. Deliberately small — two or three pages of application —
but it will be treated as a real repo and carried forward into later sessions, so
conventions matter more than speed. Standing rules live in CLAUDE.md file.

**Role:** You are a senior Django and React engineer on a billing team.

**Instructions:**
1. Define three models: a custom `User` with a role field (`<role values —
   e.g. admin / staff>`); `Invoice`; and `Transaction`, which is a line item with
   a required FK to `Invoice`. Invoice totals are computed from its transactions,
   not stored as a flat field.
2. Generate the migrations via `makemigrations`.
3. Build full CRUD API endpoints for all three models.
4. Build the React frontend: a login page, a dashboard, and invoice
   create/edit/list/delete against those endpoints.
5. State the verification step for each stage — what you will run to prove it works.

**Style:** Give me a numbered implementation plan first, in dependency order. No
code until I approve the plan. Keep each plan item to one line, specific enough
that I can reject it without reading further.

**Parameters:** Never hand-edit files in `migrations/` — always generate via
`makemigrations`. Nothing beyond CRUD, login and the dashboard; no extra features.
No new libraries without asking me first. Flag anything uncertain as a question
rather than choosing an answer and moving on.

**Example:** Plan items should read like "3. `Transaction` model — FK to `Invoice`
(on_delete=CASCADE), quantity, unit_price; verify: `python manage.py check` plus a
model test for the FK constraint" — not "3. Set up the models."