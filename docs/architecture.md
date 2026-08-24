# Architecture

Two services: a Django + DRF API and a React + TypeScript SPA, talking over HTTP across
`localhost:8000` ↔ `localhost:5173` in development. No message queue, no background workers, no
third service. Model fields and the computed-total rule live in `domain.md`; naming, error
shapes and permission conventions live in `conventions.md`; UI tokens live in `design-tokens.md`.

```
┌─────────────────────┐         HTTP / JSON          ┌──────────────────────┐
│  frontend/           │ ────────────────────────────▶│  backend/             │
│  React + TypeScript  │  Authorization: Token <key>   │  Django + DRF         │
│  Vite dev :5173       │◀──────────────────────────── │  :8000                │
└─────────────────────┘                                └───────────┬──────────┘
                                                                     │
                                                                     ▼
                                                          ┌──────────────────┐
                                                          │  PostgreSQL 14.18 │
                                                          └──────────────────┘
```

---

## Repository layout

```
invoice-mgmt/
├─ backend/
│  ├─ config/          settings.py, urls.py, wsgi.py
│  ├─ accounts/        User, UserManager, auth views, permissions
│  ├─ billing/         Customer, Invoice, Transaction, filters
│  └─ manage.py
├─ frontend/           Vite + React + TypeScript
├─ docs/               this directory
├─ prd.md              originating brief — superseded here wherever the two differ
├─ CLAUDE.md
└─ AGENTS.md
```

`accounts` is a separate Django app from `billing` so the swappable-user migration stays isolated
from domain migrations — mixing them is the usual regret once `AUTH_USER_MODEL` needs changing.

---

## API surface

All endpoints are under `/api/`. Auth is DRF `TokenAuthentication`; the client sends
`Authorization: Token <key>`. No registration endpoint — the first user is created with
`createsuperuser`, admins provision everyone else. Tokens do not expire; logout is a real
server-side revocation (deletes the token row), not just the client forgetting it.

| endpoint | methods | permission |
|---|---|---|
| `/api/auth/login/` | POST | `AllowAny` → `{token, user}` |
| `/api/auth/logout/` | POST | authenticated |
| `/api/auth/me/` | GET | authenticated |
| `/api/users/` | full CRUD | `ADMIN` only |
| `/api/customers/` | full CRUD | read: all roles · write: `ADMIN`, `STAFF` |
| `/api/invoices/` | full CRUD | scoped — see `conventions.md` § Permissions |
| `/api/invoices/extract/` | POST (multipart) | `ADMIN`, `STAFF` — writes no invoice |
| `/api/transactions/` | full CRUD | scoped via parent invoice |
| `/api/dashboard/` | GET | authenticated, scoped |

Pagination is `PageNumberPagination` at 20/page. Invoices and customers additionally support
`SearchFilter`, `OrderingFilter` and `django-filter` (`?overdue=true`, `?mine=true` on invoices).

### Invoice write shape

Invoices and their line items are written together in a single nested request, wrapped in
`transaction.atomic()` — one Save button, one request, all or nothing:

```json
POST /api/invoices/
{
  "customer": 3, "issue_date": "2026-08-21", "due_date": "2026-09-20", "notes": "",
  "transactions": [
    {"description": "Design work", "quantity": "2.5", "unit_price": "100.00"},
    {"description": "Hosting",     "quantity": "1",   "unit_price": "50.00"}
  ]
}
→ 201 { "id": 7, "invoice_number": "INV-00007", "customer": {...}, "total": "300.00",
        "transactions": [ {"id": 12, "line_total": "250.00", ...}, ... ] }
```

`invoice_number` and `total` are read-only. **Update is replace-all**: `update()` deletes the
invoice's existing transactions and recreates them from the payload — simple and correct, but it
churns `Transaction` primary keys on every save. Never hold a long-lived reference to a
line-item ID. `/api/transactions/` exists as a standalone ViewSet for completeness; the frontend
only ever writes through the nested path above.

### PDF ingest

```
FE  --multipart PDF-->  /api/invoices/extract/  --PDF as a file-->  OpenAI
                                                <--structured JSON--
FE  <--fields to review--
FE  --reviewed data-->  POST /api/invoices/  -->  DB
```

Two requests with a human between them. `extract/` is an `@action` on `InvoiceViewSet` rather than
its own `path()`, so it inherits `RolePermission` and the router places it ahead of
`invoices/<pk>/` — registered separately it would be swallowed by the detail route, whose lookup
regex matches `extract` happily.

Three things about it are worth knowing before touching it:

- **It writes no invoice and no line items.** Saving is the ordinary `POST /api/invoices/`; there
  is deliberately no second write path. It *does* create a `Customer` when the supplier matches
  nothing on file — the one persistence side-effect, and a knowing reversal of the spec's original
  rule. See `docs/specs/2026-08-ocr-ingest.md` open question 4.
- **The request blocks for the whole model call.** There is no job queue in this project, so a
  multi-page invoice can hold a worker for the better part of a minute
  (`OPENAI_TIMEOUT_SECONDS`, default 90). Fine for one user on `runserver`; it is the first thing
  that would need rethinking under load.
- **The uploaded file is never stored.** It is read into memory, base64'd inline into the request,
  and dropped. No `MEDIA_ROOT`, no `FileField`, no migration — and nothing left in OpenAI's file
  storage either.

`billing/extraction.py` holds the OpenAI adapter and imports no ORM: it takes bytes, returns a
dict, and can be exercised from `manage.py shell` without a database. Resolving the extracted
supplier to a `Customer` is the view's job, not its.

### Dashboard

```json
GET /api/dashboard/
{ "invoice_count": 42, "grand_total": "18450.00", "overdue_count": 3,
  "customer_count": 11, "recent_invoices": [ ... ] }
```

Scoped by role identically to `/api/invoices/`. Aggregation happens in the database — see
`domain.md` for why the SQL has to round per-line to agree with the invoice list.

---

## Frontend

### Routes

| route | page | wireframe |
|---|---|---|
| `/login` | login form | 2b split brand panel |
| `/` | dashboard | 1a tiles then recent list |
| `/invoices` | invoice list | 1c full-width table |
| `/invoices/new` | create | 1f single form, sticky summary |
| `/invoices/upload` | PDF chooser, then extracting / failed | 3a · 3b · 3d |
| `/invoices/upload/review` | check the extracted fields before saving | 3c |
| `/invoices/:id` | read-only detail | 1h |
| `/invoices/:id/edit` | edit | 1f (same component) |
| `/customers` | customer list + CRUD | none drawn — matches 1c's table rhythm |

### Structure

```
frontend/src/
├─ api/          client.ts (fetch wrapper, token, 401 handling), customers.ts,
│                extraction.ts — SIMULATED, see docs/specs/2026-08-ocr-ingest.md
├─ auth/         AuthContext.tsx — token in localStorage, user hydrated from /api/auth/me/
├─ components/   AppShell.tsx, ProtectedRoute.tsx, UploadDraftRoute.tsx
├─ lib/          money.ts — display-only arithmetic; server value is always authoritative
├─ pages/        Login, Dashboard, InvoiceList, InvoiceForm, InvoiceDetail, CustomerList,
│                InvoiceUpload, InvoiceUploadReview
├─ styles/       tokens.css — verbatim port, see design-tokens.md
└─ types.ts      hand-maintained mirror of the DRF serializers, plus one block
                 (ExtractionResult) that mirrors an endpoint that does not exist yet
```

`UploadDraftRoute` is a layout route, not a page: the two upload screens are two routes sharing
one in-memory draft (a `File` cannot be put in a URL), so reaching the review screen without one
redirects back to the chooser.

`types.ts` has no source of truth beyond the serializers themselves — when a serializer field
changes, this file changes with it in the same commit.

---

## Decisions and deviations from `prd.md`

Recorded here because they change the shape of the system, not just a model field (those are in
`domain.md`).

1. **A fourth model, `Customer`** — see `domain.md`.
2. **No automated tests.** Verification is `manage.py check`, `makemigrations --check --dry-run`,
   the Django shell, and `curl` against a running server. Consequence: the computed-total rule and
   the role-scoping rules in `conventions.md` have no regression safety net. Worth revisiting if
   the codebase keeps growing — see `docs/specs/` for how a new feature should state its own
   verification plan given this constraint.
3. **A `/api/dashboard/` endpoint**, not named in the original brief — needed once the `status`
   field was dropped and the dashboard had nothing else to aggregate.
4. **A `/customers` page**, reversing an earlier decision to manage customers only through the
   Django admin. Reversed when UI wireframes arrived showing a Customers nav item on every
   screen. The API already supported it; no backend change was needed.

---

## Build history

The system was built in 15 dependency-ordered steps, each with its own verification command, then
restyled onto the SkilloVilla design system (`design-tokens.md`) in a second pass. All steps are
complete. Kept here as a record of build order, not as a task list.

<details>
<summary>Steps 1–15 (click to expand)</summary>

1. Scaffold `backend/` (`config`, `accounts`, `billing` apps), `requirements.txt`, `.env.example` — verify: `manage.py check`.
2. Postgres via `django-environ`; `AUTH_USER_MODEL` set before the first migration — verify: `manage.py check` + `dbshell` connects.
3. `accounts.User` + `UserManager` — verify: `migrate`, then `createsuperuser` with an email.
4. `billing.Customer` — verify: `migrate` + create one in `shell`.
5. `billing.Invoice` — verify: an invoice with no lines reports `total == Decimal("0.00")`.
6. `billing.Transaction` — verify: FK required, two lines sum correctly, cascade delete works.
7. Admin registrations + custom `UserAdmin` — verify: `/admin/` loads without a 500.
8. DRF, token auth, CORS, `login`/`logout`/`me` — verify: `curl` login returns a token; wrong password is 401.
9. `RolePermission` + scoped `get_queryset` — verify: `curl` as each role.
10. `CustomerViewSet` + `UserViewSet`, `ProtectedError` → 400 — verify: delete-with-references returns 400 not 500.
11. `InvoiceViewSet`, nested writable serializer, replace-all update — verify: nested POST returns computed `total`.
12. `TransactionViewSet` + `/api/dashboard/` — verify: dashboard total cross-checked against the invoice list.
13. Scaffold `frontend/` — verify: `tsc --noEmit` clean, login stores a token and redirects.
14. Login + dashboard pages — verify: in the browser, bad credentials show an error.
15. Invoice list + create/edit/delete — verify: in the browser, create/edit/delete an invoice.

</details>
