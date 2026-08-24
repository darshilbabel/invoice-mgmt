# backend/CLAUDE.md

Django + DRF specifics. Repo-wide rules are in the root `CLAUDE.md` / `AGENTS.md`; the model
fields and the computed-total rule are in `../docs/domain.md`; permission and error conventions
are in `../docs/conventions.md`. This file is what those conventions look like as code.

## App layout

- `config/` — settings, root urlconf, the global `api_exception_handler`.
- `accounts/` — `User`, `UserManager`, `Role`, auth views (`LoginView`/`LogoutView`/`MeView`),
  `permissions.py` (`RolePermission`, `scope_to_role`, `RoleScopedQuerysetMixin`).
- `billing/` — `Customer`, `Invoice`, `Transaction`, their serializers, viewsets, `filters.py`.

`accounts` and `billing` are separate apps specifically so the swappable-user migration history
never mixes with domain migrations.

## Models

- Money fields are `DecimalField`; never `FloatField`. `Transaction.line_total` and
  `Invoice.total` are properties, not columns — see `../docs/domain.md` before changing either.
- `on_delete=PROTECT` on both `Invoice.customer` and `Invoice.created_by`. If you add a new FK
  that should behave the same way, you don't need to add error handling for it —
  `config.exceptions.api_exception_handler` catches `ProtectedError` globally.
- List querysets that touch `Invoice.total` **must** `.prefetch_related("transactions")` (and
  usually `.select_related("customer", "created_by")` too) or it's an N+1.

## Serializers

- The pattern for a nested writable resource is `InvoiceSerializer` in `billing/serializers.py` —
  `create()`/`update()` wrapped in `transaction.atomic()`, child rows replaced wholesale on
  update. Follow that shape for any new nested write; don't invent a partial-update-of-children
  scheme.
- A field that is computed (never persisted) is declared explicitly read-only
  (`invoice_number`, `total`, `line_total`) — never rely on `Meta.fields` alone to make something
  read-only when it's a `@property`.
- A serializer field that references a *scoped* model and is writable (e.g.
  `TransactionDetailSerializer.invoice`) must validate ownership in `validate_<field>()` itself.
  `RoleScopedQuerysetMixin` only narrows what `get_queryset()` returns — it does nothing for a
  `PrimaryKeyRelatedField`, which by default spans every row of the target model.

## `billing/extraction.py`

The OpenAI adapter. **It imports no ORM, deliberately** — bytes in, dict out — so it can be driven
from `manage.py shell` with no database and so replacing the engine touches one file. Resolving the
extracted supplier to a `Customer` row is `views._resolve_customer`'s job, not its.

Two rules for anything you change in there:

- **Normalise at the edge, don't trust the model.** `to_money()` strips currency symbols and
  separators and quantizes the same way `Transaction.line_total` does, so a value that leaves this
  module is already in the form the API contract promises. A value it cannot parse is **not**
  silently zeroed — it becomes a safe default *and* its path is added to `low_confidence`, so the
  review screen flags it for a human instead of showing a confident wrong number.
- **Structured Outputs' strict mode cannot express arbitrary object keys.** That is why per-field
  notes come back as a list of `{path, note}` pairs and get folded into a dict here. If you add a
  field, every property must also be listed in `required`; optional means `["string", "null"]`.

`ExtractionError` carries a `reason` matching the union in `frontend/src/types.ts`. Views turn it
into a 400 with a readable `detail` — never let one become a 500.

## Permissions

Read `../docs/conventions.md` § Permissions before adding an endpoint. In short: use
`RolePermission` for the read/write axis, `RoleScopedQuerysetMixin` (viewsets) or `scope_to_role()`
directly (anything else, e.g. `DashboardView`) for the ownership axis. Never write a second
STAFF-filtering `if user.role == Role.STAFF: ...` — call the shared function.

## Admin

`accounts/admin.py`'s custom `UserAdmin` is **mandatory**, not decorative: Django's default
`UserAdmin` references `username`, which this model doesn't have, so `/admin/` 500s without it.
`billing/admin.py` is deliberately minimal (`admin.site.register`, no inlines) except
`CustomerAdmin`, which gets `search_fields` because the admin is a real workflow surface, not
just a debugging tool.

## Verification

No test suite (`../docs/conventions.md`). For any change here:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run   # fails loudly if a model changed silently
```

then exercise the actual behavior — `manage.py shell` for model/queryset logic, `curl` against
`runserver` for anything that crosses the API boundary. A green `check` proves the code imports;
it proves nothing about whether it's correct.

## settings.py

All the secret keys which are used in settings.py must come from .env file only. Otherwise throw an error.