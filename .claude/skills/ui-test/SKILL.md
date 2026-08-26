---
name: ui-test
description: Drive the invoice-mgmt UI in a real browser with Playwright MCP — start both servers, sign in as a role, and walk a flow end to end. Use when asked to test the UI, check a screen, reproduce a bug in the browser, or verify a change visually. This project has no test suite, so a browser pass IS the regression check.
---

# Browser-testing invoice-mgmt

This project has **no automated tests** — a deliberate call recorded in `docs/architecture.md`'s
decision log. A browser pass is not a nice-to-have here; it is the only thing standing between a
change and a regression. Treat it accordingly.

Use the **Playwright MCP** tools (`mcp__playwright__*`). If they are not in the tool list, the MCP
server has not loaded — say so and stop rather than falling back to another browser tool.

## 1. Get both servers up first

Check before starting: a stale server is the most common cause of a confusing failure.

```bash
lsof -ti:8000 -sTCP:LISTEN   # backend
lsof -ti:5173 -sTCP:LISTEN   # frontend
```

```bash
# backend — from backend/, venv at the repo root. Runs on :8000.
../.venv/bin/python manage.py runserver 8000

# frontend — from frontend/. Runs on :5173.
npm run dev
```

Start them with `run_in_background: true`, then poll until they answer. `curl -o /dev/null -w
"%{http_code}" http://localhost:8000/api/auth/me/` returning **401** means the backend is up and
correctly refusing an unauthenticated request.

**Never start the backend with an inline `OPENAI_API_KEY=...`.** Anything exported into the
process wins over `.env` (`django-environ` does not overwrite what is already set), so a
placeholder passed on the command line silently disables extraction and every upload fails with
"The extraction service is unavailable right now." If the server will not boot because the key is
missing, that is the actual bug — fix the environment, do not paper over it.

## 2. Sign in

`/login` — email and password, no username.

| email | password | role | can |
|---|---|---|---|
| `test-admin@invoice.local` | `TestAdmin2026!` | ADMIN | everything, sees all invoices |
| `test-staff@invoice.local` | `TestStaff2026!` | STAFF | writes, but sees **only its own** invoices |
| `test-viewer@invoice.local` | `TestViewer2026!` | VIEWER | read-only |

Roles are the thing most worth checking and easiest to break, because the rules live in three
places at once (`RolePermission`, `scope_to_role`, and the frontend's `canWrite`). A STAFF user
reaching another owner's invoice must get a **404, not a 403** — that is deliberate, so a 403 does
not confirm the row exists.

## 3. Routes

| route | what to look at |
|---|---|
| `/` | four tiles, then recent invoices |
| `/invoices` | table, filter bar, two-step inline delete, `Upload PDF` + `New invoice` |
| `/invoices/new` · `/invoices/:id/edit` | line items, sticky running-total bar |
| `/invoices/:id` | read-only detail |
| `/invoices/upload` | choose a PDF → progress → failure |
| `/invoices/upload/review` | check extracted fields, then save |
| `/customers` | the one screen with no wireframe |

## 4. The PDF upload flow — where the real risk is

`docs/specs/2026-08-ocr-ingest.md` is the spec. Four things deserve deliberate attention:

1. **The two totals** at the foot of the line items — the total printed on the PDF against the sum
   of the extracted rows. Them agreeing is the single best signal nothing was misread; them
   disagreeing is the entire reason that line exists. Edit a quantity and confirm the row total,
   the grand total and the agreement line all move together.
2. **The customer card.** *Matched* means an existing row; **Created means a row now exists in the
   database whether or not you go on to save.** Check `/customers` afterwards. A wrong row created
   by one test will then match *by name* on the next one and silently mask the very bug you are
   chasing — clean up test-created customers before re-running.
3. **Money is never reformatted.** Values are strings from the API to the input and back. If a
   total renders as `18000` rather than `18000.00`, or a JSON money field comes back as a bare
   number, a `DecimalField` was skipped somewhere.
4. **Amber means low confidence, and nothing else.** It should appear only on the review screen,
   and the marker should clear once you edit the field it flags. Overdue is `--danger` red
   everywhere, including there.

Expect the extract call to take **5–15 seconds** — it is one blocking request wrapping a model
call, with no job queue behind it. Do not treat a slow response as a hang; the client timeout is
90s (`OPENAI_TIMEOUT_SECONDS`).

To test a failure path, upload a non-PDF renamed `.pdf` — the server checks the `%PDF-` magic
bytes, so it lands on the failure screen with a real message.

## 5. What to check on any UI change

- **Keyboard only.** Every control reachable, and the 3px focus ring never removed — that is a
  hard rule in `docs/design-tokens.md`. The upload drop zone is the one to watch: it wraps a real
  `<input type="file">` so it must be reachable without a mouse.
- **The console.** A React key warning or a failed request often does not show visually.
- **The design audit**, after any CSS change — three greps, listed in `docs/design-tokens.md`.
  Quote the `--include` patterns or zsh expands them and every grep looks clean.

## 6. Reporting

Say what you actually observed, and name the screen and the step. If something failed, give the
console or network detail rather than a summary of it. If a check could not be run — no server, no
sample PDF, a route that would not load — say that explicitly instead of quietly dropping it from
the report.
