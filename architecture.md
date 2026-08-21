# Architecture

Invoice management system — Django + DRF + PostgreSQL backend, React + TypeScript frontend.

This document is the settled design contract. It was produced by walking the design tree
decision by decision before any code was written, so later sessions build against it rather
than re-deciding as they go. Where a decision departs from `prd.md`, it is marked
**[deviation]** and the reasoning is recorded — none of these are drift.

---

## 1. Stack and dependencies

| | |
|---|---|
| Backend | Django, Django REST Framework, PostgreSQL |
| Frontend | React + TypeScript, built with Vite |
| Auth | DRF `TokenAuthentication` |

**Python** — `django`, `djangorestframework`, `psycopg[binary]`, `django-cors-headers`,
`django-filter`, `django-environ`.

**Django is pinned to 5.2 LTS, and the pin is a ceiling, not a preference.** The local
PostgreSQL server is 14.18; Django 6.1 declares `minimum_database_version = (15,)` and refuses
to connect. Django 5.2 and 6.0 both accept PostgreSQL 14. 5.2 was chosen for its LTS support
window (to April 2028). **Raising this pin requires upgrading PostgreSQL first** — and that
server hosts nine unrelated project databases.

One consequence of pinning to 5.2: its global `DEFAULT_AUTO_FIELD` is the 32-bit `AutoField`.
Both `settings.DEFAULT_AUTO_FIELD` and each app's `default_auto_field` are set explicitly to
`BigAutoField`. Do not remove them — Django 6.x made that the global default and dropped it from
its templates, but under 5.2 their absence silently yields 32-bit primary keys.

**JavaScript** — `react`, `react-dom`, `react-router-dom`, `typescript`, `vite`.

Nothing beyond these lists without explicit approval. In particular the frontend uses native
`fetch` (no axios) and React Context (no state library).

`django-cors-headers` is not a convenience: Vite serves on `:5173` and Django on `:8000`, so
every API call is cross-origin and the browser blocks it without CORS headers.

---

## 2. Repository layout

```
invoice-mgmt/
├─ backend/
│  ├─ config/          settings.py, urls.py, wsgi.py
│  ├─ accounts/        User, UserManager, auth views
│  ├─ billing/         Customer, Invoice, Transaction
│  └─ manage.py
├─ frontend/           Vite + React + TypeScript
├─ architecture.md
├─ prd.md
└─ CLAUDE.md
```

`accounts` is a separate app so the swappable-user migration stays isolated from domain
migrations. Mixing them is the usual regret once `AUTH_USER_MODEL` needs changing.

---

## 3. Models

### 3.1 `accounts.User`

Hand-rolled on `AbstractBaseUser` + `PermissionsMixin`. Login is by email; there is no
`username` field.

| field | type | notes |
|---|---|---|
| `email` | `EmailField(unique=True)` | `USERNAME_FIELD` |
| `full_name` | `CharField(max_length=150)` | listed in `REQUIRED_FIELDS` |
| `role` | `CharField(max_length=10, choices=Role)` | default `STAFF` |
| `is_active` | `BooleanField(default=True)` | |
| `is_staff` | `BooleanField(default=False)` | gates `/admin/`; set together with `role=ADMIN` |
| `date_joined` | `DateTimeField(auto_now_add=True)` | |

```python
class Role(models.TextChoices):
    ADMIN  = "ADMIN",  "Admin"
    STAFF  = "STAFF",  "Staff"
    VIEWER = "VIEWER", "Viewer"
```

A custom `UserManager` is required — `create_user(email, password, **extra)` and
`create_superuser(...)`, the latter forcing `role=ADMIN`, `is_staff=True`, `is_superuser=True`.

`role` and `is_staff` are independent on purpose: `role` drives API permissions, `is_staff`
drives Django admin access.

### 3.2 `billing.Customer` — **[deviation]**

`prd.md` fixes the model count at three. A fourth was added deliberately so invoices reference a
customer record instead of re-typing customer details on every invoice.

| field | type |
|---|---|
| `name` | `CharField(max_length=200)` |
| `email` | `EmailField(blank=True)` |
| `company_name` | `CharField(max_length=200, blank=True)` |
| `billing_address` | `TextField(blank=True)` |
| `created_at` / `updated_at` | `DateTimeField(auto_now_add=…/auto_now=…)` |

### 3.3 `billing.Invoice`

| field | type | notes |
|---|---|---|
| `customer` | `FK(Customer, on_delete=PROTECT, related_name="invoices")` | see 3.5 |
| `issue_date` | `DateField(default=timezone.localdate)` | |
| `due_date` | `DateField()` | |
| `notes` | `TextField(blank=True)` | |
| `created_by` | `FK(AUTH_USER_MODEL, on_delete=PROTECT, related_name="invoices")` | owner, for STAFF scoping |
| `created_at` / `updated_at` | | |

There is **no** `status` field, **no** stored `invoice_number`, and **no** stored total.

```python
@property
def invoice_number(self):
    return f"INV-{self.pk:05d}"          # "INV-00042"

@property
def total(self):
    return sum((t.line_total for t in self.transactions.all()), Decimal("0.00"))
```

`invoice_number` is derived from the primary key, so collisions are structurally impossible and
there is no sequence to lock. The tradeoffs, accepted knowingly: numbering has gaps if invoices
are deleted, it leaks the row count, and it cannot match an external numbering convention.
Because it is not a column, searching by "INV-00042" means parsing the digits back to a PK in
the filter layer — a plain `icontains` will not work.

### 3.4 `billing.Transaction`

The invoice line item.

| field | type |
|---|---|
| `invoice` | `FK(Invoice, on_delete=CASCADE, related_name="transactions")` — required |
| `description` | `CharField(max_length=255)` |
| `quantity` | `DecimalField(max_digits=10, decimal_places=2)` |
| `unit_price` | `DecimalField(max_digits=12, decimal_places=2)` |
| `created_at` | `DateTimeField(auto_now_add=True)` |

```python
@property
def line_total(self):
    return self.quantity * self.unit_price
```

`quantity` is a Decimal rather than an integer so partial units (2.5 hours) are billable.
No tax and no discount fields — one multiplication is the entire money model.

### 3.5 Deleting a customer

`on_delete=PROTECT`. An invoice always renders its customer's *current* details, so correcting a
typo fixes it everywhere. The accepted cost is that editing a customer retroactively rewrites
what past invoices say — there is no frozen snapshot.

Deleting a customer that has invoices raises `ProtectedError`. The API catches this and returns
**400 with a readable message**, never an unhandled 500.

---

## 4. How totals are computed

Totals are computed from transactions and never stored. This is the load-bearing rule of the
whole system.

The implementation is the Python property in 3.3, combined with
`.prefetch_related("transactions")` on any list queryset:

```python
queryset = Invoice.objects.select_related("customer").prefetch_related("transactions")
```

Fifty invoices cost **2 queries, not 51**. One code path serves the API, the admin, the shell
and any script — there is no second SQL implementation of the rule that could drift from it.
Summing in Python also keeps exact `Decimal` arithmetic with no float involved.

**Consequence to remember:** `total` is not a SQL column, so `?ordering=total` and
`?total__gt=…` are not available on the API. Sorting by total is not offered.

The single exception is `grand_total` on the dashboard, which is one scalar over the whole set
and so is aggregated in SQL:

```python
Coalesce(
    Sum(Round(F("transactions__quantity") * F("transactions__unit_price"), 2)),
    Decimal("0.00"),
)
```

Two details, both load-bearing:

- **`Round(..., 2)` goes *inside* the `Sum`.** `line_total` quantizes each line to cents before
  `total` adds them, so the SQL has to round per line too. Summing raw 4dp products and rounding
  once at the end gives a different answer: three lines of `0.25 x 0.50` are `0.39` per-line but
  `0.38` sum-first. That is a real cent of drift between the dashboard and the invoice list.
- **`Coalesce` matters** — a bare `Sum` returns `None`, not zero, when there is nothing to sum.

The result is rendered through a DRF `DecimalField` rather than placed in the response dict as a
raw `Decimal`. `COERCE_DECIMAL_TO_STRING` only applies to serializer fields, so a bare `Decimal`
renders as a JSON *number* (`850.0`) and breaks the money-as-strings rule in section 7.

---

## 5. API

All endpoints are under `/api/`. Authentication is DRF `TokenAuthentication`
(`rest_framework.authtoken`); the client sends `Authorization: Token <key>`.

| endpoint | methods | permission |
|---|---|---|
| `/api/auth/login/` | POST | `AllowAny` → `{token, user}` |
| `/api/auth/logout/` | POST | authenticated — deletes the token row server-side |
| `/api/auth/me/` | GET | authenticated → `{id, email, full_name, role}` |
| `/api/users/` | list, create, retrieve, update, destroy | `ADMIN` only |
| `/api/customers/` | full CRUD | read: all roles · write: `ADMIN`, `STAFF` |
| `/api/invoices/` | full CRUD | scoped, see 5.1 |
| `/api/transactions/` | full CRUD | scoped via parent invoice |
| `/api/dashboard/` | GET | authenticated |

There is **no registration endpoint**. The first user is created with `createsuperuser`;
admins provision everyone else. No unauthenticated write path exists anywhere in the API.

Tokens do not expire. Logout is a real server-side action, not just clearing localStorage.

Pagination is `PageNumberPagination` at 20 per page. Invoices and customers additionally use
`SearchFilter`, `OrderingFilter` and `django-filter`.

### 5.1 Permissions and scoping

One permission class covers both axes — read/write and ownership:

| | list / retrieve | create | update / delete | manage users | Django admin |
|---|---|---|---|---|---|
| `ADMIN` | all | yes | any | yes | yes |
| `STAFF` | own only | yes | own only | no | no |
| `VIEWER` | all | no | no | no | no |

- `VIEWER` is restricted to `SAFE_METHODS` but sees everything.
- `STAFF` querysets for invoices and transactions are filtered to `created_by=request.user`.
- `created_by` is set from `request.user` in `perform_create()` and is **never** accepted from
  the request body.
- `role` is only writable through `/api/users/` by an `ADMIN` — a user can never escalate
  themselves.

### 5.2 Invoice write shape

Invoices and their line items are written together in a single nested request, wrapped in
`transaction.atomic()`. This mirrors the UI: one Save button, one request, all or nothing —
a half-built invoice is never persisted.

```json
POST /api/invoices/
{
  "customer": 3,
  "issue_date": "2026-08-21",
  "due_date": "2026-09-20",
  "notes": "",
  "transactions": [
    {"description": "Design work", "quantity": "2.5", "unit_price": "100.00"},
    {"description": "Hosting",     "quantity": "1",   "unit_price": "50.00"}
  ]
}

201 Created
{
  "id": 7,
  "invoice_number": "INV-00007",
  "customer": {"id": 3, "name": "Acme Corp", ...},
  "issue_date": "2026-08-21",
  "due_date": "2026-09-20",
  "total": "300.00",
  "transactions": [ {"id": 12, "line_total": "250.00", ...}, ... ]
}
```

`invoice_number` and `total` are **read-only** serializer fields.

**Update semantics are replace-all**: `update()` deletes the invoice's existing transactions and
recreates them from the payload. Simple and correct, but it churns `Transaction` primary keys on
every save — do not build anything that holds a long-lived reference to a line-item ID.

`/api/transactions/` is registered as a standalone ViewSet to satisfy the PRD's "CRUD endpoints
for all models", even though the React app only ever writes through the nested path.

### 5.3 Dashboard — **[deviation]**

A fourth endpoint the PRD did not name. It exists because dropping the `status` field left the
dashboard page with nothing meaningful to aggregate.

```json
GET /api/dashboard/
{
  "invoice_count": 42,
  "grand_total": "18450.00",
  "overdue_count": 3,          // due_date < today
  "customer_count": 11,
  "recent_invoices": [ ... ]   // 5 most recent
}
```

Scoped by role identically to `/api/invoices/` — a `STAFF` user sees totals for their own
invoices only. Aggregation happens in the database, not in React.

---

## 6. Django admin

Deliberately minimal: plain `admin.site.register()` for `Customer`, `Invoice` and `Transaction`.
No inlines, so line items are added on their own page rather than alongside their invoice, and
the computed total is not surfaced in the admin.

**A custom `UserAdmin` is mandatory, not optional.** Django's default `UserAdmin` references
`username`, which this model does not have, so `/admin/` returns a 500 without one. It needs:

- `add_form` / `form` subclasses built around `email` instead of `username`
- rewritten `fieldsets` and `add_fieldsets` exposing `role`
- `ordering = ("email",)`
- `list_display = ("email", "full_name", "role", "is_active", "is_staff")`

`CustomerAdmin` gets `search_fields` despite the minimal posture, because the admin is the only
place customers are created — the React app does not manage them.

Admin access requires `is_staff=True`, which is set alongside `role=ADMIN`.

---

## 7. Frontend

### Routes

| route | page |
|---|---|
| `/login` | login form |
| `/` | dashboard |
| `/invoices` | invoice list |
| `/invoices/new` | create |
| `/invoices/:id/edit` | edit |

There is no customers page. The invoice form's customer `<select>` is populated from
`/api/customers/`; customers themselves are created in the Django admin.

### Structure

```
frontend/src/
├─ api/client.ts        fetch wrapper: attaches Token header, redirects to /login on 401
├─ auth/AuthContext.tsx token in localStorage, user hydrated from /api/auth/me/
├─ components/ProtectedRoute.tsx
├─ pages/               Login · Dashboard · InvoiceList · InvoiceForm
└─ types.ts             hand-maintained mirror of the DRF serializers
```

`types.ts` is maintained by hand against the serializers. Whenever a serializer field changes,
the matching interface must change with it — that pairing is the reason TypeScript is here.

### Money handling

DRF serializes `Decimal` as a **string**. Money stays a string end to end — in the API client,
in `types.ts`, and in component state. It is parsed into a JS `number` only for transient
display arithmetic (the form's running subtotal), never for anything sent back to the server.
The server's `total` is always authoritative; the client-side running total is a preview.

---

## 8. Deviations from `prd.md`

Each was an explicit decision, not an oversight.

1. **A fourth model, `Customer`.** The PRD specifies three. Chosen so invoices reference a
   customer record rather than duplicating customer details per invoice. Cost: no snapshot
   semantics — editing a customer changes what historical invoices display.

2. **No automated tests.** Verification is `manage.py check`,
   `makemigrations --check --dry-run`, the Django shell, and `curl` against a running server.
   The PRD's own worked example calls for "a model test for the FK constraint". The practical
   consequence: **the computed-total rule in section 4 has nothing guarding it** as this repo is
   carried across later sessions, and there is no regression safety net for the role scoping in
   5.1. Worth revisiting if the repo grows.

3. **A `/api/dashboard/` endpoint.** Not named in the PRD; needed once `status` was dropped.

Also worth noting as a scope choice rather than a deviation: `Invoice` has no `status` field, so
there is no way to record whether an invoice has been paid. This was chosen for minimality and
is the most likely thing to be added first.

---

## 9. Implementation plan

Dependency order. Every item names what proves it works.

1. Scaffold `backend/` (`config` project, `accounts` + `billing` apps), `requirements.txt`, `.env.example`; verify: `python manage.py check`.
2. Postgres config via `django-environ`, and `AUTH_USER_MODEL = "accounts.User"` set **before any migration is run**; verify: `python manage.py check` plus `python manage.py dbshell` connects.
3. `accounts.User` + `UserManager` — `AbstractBaseUser`, `PermissionsMixin`, email login, `Role` choices; verify: `makemigrations accounts`, `migrate`, then `createsuperuser` completes using an email.
4. `billing.Customer` with the four fields plus timestamps; verify: `makemigrations billing`, `migrate`, create one in `manage.py shell`.
5. `billing.Invoice` — `customer` FK `PROTECT`, `created_by` FK, dates, `invoice_number` and `total` properties; verify: in `shell`, a saved invoice with no lines reports `total == Decimal("0.00")` and `invoice_number == "INV-00001"`.
6. `billing.Transaction` — FK to `Invoice` `CASCADE`, `description`, `quantity`, `unit_price`, `line_total`; verify: in `shell`, saving without an invoice raises `IntegrityError`, two lines sum correctly into `invoice.total`, and deleting the invoice removes both lines.
7. Minimal admin registrations plus the custom `UserAdmin`; verify: `/admin/` loads without a 500, and a user and a customer can both be created through it.
8. DRF, token auth and CORS wired into settings; `login` / `logout` / `me` views; verify: `curl` login returns a token, `/api/auth/me/` echoes the correct role, a wrong password returns 401.
9. `RolePermission` class and the scoped `get_queryset` mixin; verify: `curl` as each role — `STAFF` sees only its own invoices, `VIEWER` gets 403 on POST, `ADMIN` sees everything.
10. `CustomerViewSet` and `UserViewSet`, including `ProtectedError` → 400 handling; verify: `curl` full CRUD on both; deleting a customer that has invoices returns 400 with a message, not a 500.
11. `InvoiceViewSet` with the nested writable serializer, `prefetch_related`, and replace-all update; verify: `curl` a nested POST returns the computed `total`; a follow-up PUT with one fewer line drops that line.
12. Standalone `TransactionViewSet` and `/api/dashboard/`; verify: `curl` the dashboard and cross-check its `grand_total` against summing the invoice list by hand.
13. Scaffold `frontend/` (Vite `react-ts`), `client.ts`, `types.ts`, `AuthContext`, `ProtectedRoute`; verify: `npm run dev` starts and `npx tsc --noEmit` is clean; logging in stores a token and redirects.
14. Login and dashboard pages; verify: in the browser, bad credentials show an error, good credentials land on a dashboard showing the same numbers as step 12.
15. Invoice list plus create/edit/delete with the line-item editor; verify: in the browser, create an invoice with two lines and confirm the displayed total matches the API response, edit it to remove a line, then delete it.
