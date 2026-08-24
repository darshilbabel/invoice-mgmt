# Domain model

The business objects this system is built around, and the one rule that governs money in it.
For where these live in the API and how permissions apply to them, see `architecture.md`. For
naming and error-handling conventions, see `conventions.md`.

---

## Entities

### `accounts.User`

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

`role` and `is_staff` are independent on purpose: `role` drives API permissions, `is_staff`
drives Django admin access. A custom `UserManager` is required —
`create_user(email, password, **extra)` and `create_superuser(...)`, the latter forcing
`role=ADMIN`, `is_staff=True`, `is_superuser=True`.

### `billing.Customer` — **[deviation from `prd.md`]**

`prd.md` fixes the model count at three. A fourth was added deliberately so invoices reference a
customer record instead of re-typing customer details on every invoice.

| field | type |
|---|---|
| `name` | `CharField(max_length=200)` |
| `email` | `EmailField(blank=True)` |
| `company_name` | `CharField(max_length=200, blank=True)` |
| `billing_address` | `TextField(blank=True)` |
| `created_at` / `updated_at` | `DateTimeField(auto_now_add=…/auto_now=…)` |

**Rows can originate from extraction.** `POST /api/invoices/extract/` matches the supplier printed
on an uploaded PDF against `email`, then `name`/`company_name`, and **creates the row when nothing
matches** — so a `Customer` can exist that no one typed in, named from a misread PDF, before any
invoice is saved. See `docs/specs/2026-08-ocr-ingest.md` open question 4.

**Deleting a customer is `on_delete=PROTECT`.** An invoice always renders its customer's
*current* details, so correcting a typo fixes it everywhere — the accepted cost is that editing
a customer retroactively rewrites what past invoices display; there is no frozen snapshot.
Deleting a customer that has invoices raises `ProtectedError`, which the API turns into a 400
with a readable message rather than an unhandled 500 (see `conventions.md`).

### `billing.Invoice`

| field | type | notes |
|---|---|---|
| `customer` | `FK(Customer, on_delete=PROTECT, related_name="invoices")` | |
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
there is no sequence to lock. Accepted tradeoffs: numbering has gaps if invoices are deleted, it
leaks the row count, and it cannot match an external numbering convention. Because it is not a
column, searching by "INV-00042" means parsing the digits back to a PK in the filter layer — a
plain `icontains` will not work.

**Scope note:** no `status` field means there is no way to record whether an invoice has been
paid. Chosen for minimality; it is the most likely thing to be added next (see
`docs/specs/2026-08-ocr-ingest.md` for the currently active ticket instead).

### `billing.Transaction`

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
    return (self.quantity * self.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

`quantity` is a `Decimal` rather than an integer so partial units (2.5 hours) are billable. No
tax and no discount fields — one multiplication is the entire money model. `line_total` is
quantized explicitly: raw Decimal multiplication produces a variable number of decimal places
(`2.5 * 100.00 = 250.000`), and every consumer of this value depends on it always being exactly
2dp — see the rounding rule below.

---

## The rule that matters most

**Invoice totals are computed from the invoice's transactions, never stored as a flat field.**
This is the single load-bearing rule of the whole system. There is **no automated test suite**
(a deliberate call — see `conventions.md`), so nothing guards this rule except discipline: verify
it by hand whenever you touch invoices or line items.

The implementation is the `total` property above, combined with `.prefetch_related("transactions")`
on any list queryset:

```python
queryset = Invoice.objects.select_related("customer").prefetch_related("transactions")
```

Fifty invoices cost **2 queries, not 51**. One code path serves the API, the admin and the shell
— never add a second SQL implementation of this rule that could drift from it.

**Consequence to remember:** `total` is not a SQL column, so `?ordering=total` and
`?total__gt=…` are not available on the API. Sorting by total is not offered.

### The one exception: `grand_total` on the dashboard

One scalar over the whole set, so it is aggregated in SQL rather than summed in Python:

```python
Coalesce(
    Sum(Round(F("transactions__quantity") * F("transactions__unit_price"), 2)),
    Decimal("0.00"),
)
```

Two details, both load-bearing:

- **`Round(..., 2)` goes *inside* the `Sum`.** `line_total` quantizes each line to cents before
  `total` adds them, so the SQL has to round per line too. Summing raw 4dp products and rounding
  once at the end gives a *different* answer: three lines of `0.25 × 0.50` are `0.39` per-line but
  `0.38` sum-first. That is a real cent of drift between the dashboard and the invoice list.
- **`Coalesce` matters** — a bare `Sum` returns `None`, not zero, when there is nothing to sum.

The result is rendered through a DRF `DecimalField` rather than placed in the response dict as a
raw `Decimal`. `COERCE_DECIMAL_TO_STRING` only applies to serializer fields, so a bare `Decimal`
renders as a JSON *number* (`850.0`) and breaks the money-as-strings convention (`conventions.md`).
