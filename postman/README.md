# Postman API suite

An end-to-end test suite for the `invoice-mgmt` DRF API: **92 requests, 299 assertions**, run in
about 3 seconds. It covers auth, the ADMIN/STAFF/VIEWER matrix, the computed-total rule, the
dashboard aggregate, the error contract, filtering and pagination, and the PDF-extract rejection
paths.

This repo has no automated test suite by deliberate choice (`docs/architecture.md`, decision log
#2), so verification is `manage.py check`, a shell session, and hand-run `curl`. This collection
is those `curl` checks, written down and re-runnable.

## Files

| file | what it is |
|---|---|
| `invoice-mgmt.postman_collection.json` | the suite |
| `invoice-mgmt.postman_environment.json` | `base_url` and the three role logins |
| `seed_test_users.py` | idempotent seed for those three accounts |
| `fixtures/not-a-pdf.txt` | upload fixture for the magic-byte rejection test |

## Running it

### 1. Seed the three role accounts (once)

```bash
source .venv/bin/activate
cd backend
python manage.py shell < ../postman/seed_test_users.py
```

Idempotent and additive: it `get_or_create`s `test-admin@`, `test-staff@` and
`test-viewer@invoice.local`, forces role and `is_active`, and sets the passwords in the
environment file. It never deletes anything and never touches an invoice, customer or
transaction. Override the passwords with `PM_ADMIN_PASSWORD` / `PM_STAFF_PASSWORD` /
`PM_VIEWER_PASSWORD` if you change them in the environment file too.

### 2. Start the server

```bash
cd backend && python manage.py runserver
```

### 3a. Run in the Postman GUI

Import both JSON files, select the **invoice-mgmt local** environment, then run the whole
collection with the Collection Runner. Run folders **in order** — `00 Setup` captures the tokens
everything else needs.

For the `A non-PDF is rejected on its magic bytes` request in folder 07, re-select
`postman/fixtures/not-a-pdf.txt` in the body tab once; Postman stores file paths per machine and
does not carry them through an export.

### 3b. Run headless with newman

Newman is not a dependency of this project and is not in `package.json` — `npx` fetches it on
demand:

```bash
cd postman
npx newman@6 run invoice-mgmt.postman_collection.json \
  -e invoice-mgmt.postman_environment.json \
  --working-dir fixtures
```

`--working-dir` is what makes the relative fixture path resolve. Expect
`299 assertions, 0 failed`.

## What it writes to your database

The suite creates two customers, several invoices, one throwaway user, and one standalone
transaction — then `99 Teardown` deletes all of them and asserts `invoice_count` and
`customer_count` are back to the values `00 Setup` recorded. Two consecutive runs are equally
green. The three seeded role accounts are left in place on purpose.

If a run aborts mid-way, clean up with:

```bash
cd backend && python manage.py shell <<'PY'
from billing.models import Customer, Invoice
from accounts.models import User
c = Customer.objects.filter(name__startswith="Postman ")
Invoice.objects.filter(customer__in=c).delete(); c.delete()
User.objects.filter(email__startswith="postman-").delete()
PY
```

## The folders

| folder | what it proves |
|---|---|
| `00 Setup` | Logs in as all three roles; creates the fixture customer and one ADMIN- and one STAFF-owned invoice. |
| `01 Auth` | A wrong password is **401, not 403**; the message is identical for an unknown email (no account enumeration); logout is a real server-side revocation, proved by reusing the dead token. |
| `02 Permissions and role scoping` | `/api/users/` is ADMIN-only even to read; VIEWER cannot write anywhere; STAFF sees only its own invoices and gets **404, not 403**, on someone else's; `created_by` cannot be forged through the payload; STAFF cannot attach a line item to an invoice it cannot read. |
| `03 Invoices and the money rule` | Totals are computed, never stored or echoed; every money value is a JSON **string**; replace-all update churns line-item ids; `transactions: []` wipes lines while omitting the key preserves them; and the rounding case from `docs/domain.md` — three lines of `0.25 × 0.50` total `0.39`, not `0.38`. |
| `04 Dashboard` | Shape and scoping, a delta assertion, and the big one: **`grand_total` agrees with the sum of every `Invoice.total`**. |
| `05 Error contract` | `ProtectedError` becomes a readable 400 for both a referenced customer and a referenced user — never an unhandled 500. Both DRF error shapes appear. |
| `06 Filtering, ordering and pagination` | `?overdue=true`, `?mine=true`, search, ordering both ways, the 20-row page size, and that `?ordering=total` is ignored rather than an error. |
| `07 PDF extract` | Rejection paths only — see below. |
| `08 Known gaps` | Five places the API is wrong or surprising today. See below. |
| `99 Teardown` | Deletes everything the run created and asserts the baseline is restored. |

There is also a **collection-level test on every single request**: `no server error (5xx)`. The
repo's own rule is that `ProtectedError` and `ExtractionError` are both mapped to 400 and nothing
may surface as an unhandled 500; this enforces that across all 92 requests at once.

## The `KNOWN GAP:` convention

Requests prefixed `KNOWN GAP:` assert the API's **current** behaviour at a point where it is wrong
or surprising. They are green today.

**When one goes red, the gap was fixed. Update the test — do not revert the fix.**

The five:

1. **A negative `quantity` is accepted.** Nothing bounds `quantity` or `unit_price` — no
   validator, no `CheckConstraint` in the migrations. `-0.15 × 0.10` saves and the server rounds
   it HALF UP (away from zero) to `-0.02`. Worth knowing: `frontend/src/lib/money.ts` uses
   `Math.round`, which breaks ties toward `+Infinity` and gives `-0.01` for the same input — so
   the browser's running total and the saved total disagree by a cent on any negative line,
   despite `docs/domain.md` stating that `money.ts` mirrors the server rule.
2. **`due_date` before `issue_date` is accepted.** `InvoiceSerializer` has no `validate()`, so
   backwards invoices save cleanly and then inflate the dashboard's `overdue_count`.
3. **Searching by invoice number finds nothing.** `InvoiceList.tsx` advertises
   `"Search invoice number or customer"`, but `search_fields` is
   `("customer__name", "customer__company_name", "notes")` and no `invoice_number` filter exists.
   Because `invoice_number` is derived from the pk and has no column, supporting it means parsing
   the digits back to a pk in the filter layer — an `icontains` cannot work.
4. **`?overdue=false` is a silent no-op.** `filter_overdue` returns the queryset untouched when
   the value is falsy, so it reads as "no filter" rather than "not overdue". Same for
   `?mine=false`.
5. **A GET response cannot be PUT straight back.** `to_representation()` expands `customer` and
   `created_by` into objects, but the writable fields are primary keys. A client round-tripping a
   GET into a PUT gets `"Incorrect type. Expected pk value, received dict."`

## The PDF extract endpoint

Folder 07 covers **only** the four rejection paths: no auth (401), VIEWER (403), no file (400),
and a non-PDF caught on its `%PDF-` magic bytes (400). All four short-circuit before
`extract_invoice_fields` is called, so **none of them reaches OpenAI or costs anything**.

Two further cases are deliberately **not shipped**, because neither can run reliably or freely:

- **The happy path** is a billable OpenAI call that blocks the worker for up to
  `OPENAI_TIMEOUT_SECONDS` (default 90). To try it by hand:

  ```bash
  TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login/ \
    -H 'Content-Type: application/json' \
    -d '{"email":"test-admin@invoice.local","password":"AdminPass123!"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

  curl -s -H "Authorization: Token $TOKEN" -F file=@your-invoice.pdf \
    http://localhost:8000/api/invoices/extract/ | python3 -m json.tool
  ```

  Expect money as **quoted strings**; a bare number means a `DecimalField` was skipped somewhere.
  Note that a successful extract **creates a `Customer`** when the supplier matches nothing on
  file, even if you then discard the upload — see open question 4 in
  `docs/specs/2026-08-ocr-ingest.md`.

- **The oversize rejection** needs a file above `INVOICE_UPLOAD_MAX_BYTES` (default 10 MB), which
  is not worth committing. Generate one and check it returns 400:

  ```bash
  mkfile -n 11m /tmp/too-big.pdf
  curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Token $TOKEN" \
    -F file=@/tmp/too-big.pdf http://localhost:8000/api/invoices/extract/   # expect 400
  ```

## Troubleshooting

**Every request fails with `request url is empty`** — the environment is not selected, so
`{{base_url}}` is unset. Pick **invoice-mgmt local** in the environment dropdown, or pass `-e` to
newman.

**`00 Setup` fails with 401** — the seed has not run, or the environment passwords no longer match
the seeded ones. Re-run `seed_test_users.py`.

**Folder 07's non-PDF test errors on the file** — the fixture path did not resolve. Use
`--working-dir fixtures` with newman, or re-select the file in the GUI.

**Teardown fails with 400 on a customer delete** — an invoice created by an earlier aborted run is
still referencing it (`on_delete=PROTECT`). Run the cleanup snippet above.
