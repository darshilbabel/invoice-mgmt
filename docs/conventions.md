# Conventions

Cross-cutting rules that apply regardless of which file you're editing. Model-specific rules live
in `domain.md`; service boundaries live in `architecture.md`.

---

## Dependencies

**No new library without asking first** — pip or npm. The approved lists:

- **Python** — `django` (pinned to **5.2 LTS**, see below), `djangorestframework`,
  `psycopg[binary]`, `django-cors-headers`, `django-filter`, `django-environ`, `openai`.
- **JavaScript** — `react`, `react-dom`, `react-router-dom`, `typescript`, `vite`. Native `fetch`
  (no axios). React Context (no state library).

`openai` was approved on 2026-08-24 for reading uploaded invoice PDFs
(`docs/specs/2026-08-ocr-ingest.md`). It is the **only** dependency that feature needs: the PDF is
sent to the model as a file, so there is no PDF parser and no OCR library, and there should never
be one — if extraction stops working, fix the prompt or the model, don't add `pypdf`.

**The Django pin is a ceiling, not a preference.** The local PostgreSQL is 14.18; Django 6.1
declares `minimum_database_version = (15,)` and refuses to connect. Raising the pin means
upgrading PostgreSQL first — and that server hosts other, unrelated databases. Do not bump it
without checking the PostgreSQL version first.

One consequence of the 5.2 pin: its global `DEFAULT_AUTO_FIELD` is the 32-bit `AutoField`.
`settings.DEFAULT_AUTO_FIELD` and each app's `default_auto_field` are set explicitly to
`BigAutoField` — do not remove them, their absence silently yields 32-bit primary keys.

---

## Migrations

**Never hand-edit anything under `migrations/`.** Always generate via `python manage.py
makemigrations`. If a migration looks wrong, fix the model and regenerate — don't patch the
migration file.

---

## Money

Money crosses the wire as a **string**, always. DRF's `COERCE_DECIMAL_TO_STRING` handles this
for serializer fields automatically; the one place it doesn't apply automatically is a bare
`Decimal` placed directly into a `Response` dict (the dashboard total) — that must go through a
`DecimalField.to_representation()` explicitly, or it renders as a JSON number and breaks the
contract silently.

On the frontend, money stays a string end to end — in `types.ts`, in component state, in
whatever gets sent back to the server. It is parsed into a JS `number` only for transient display
arithmetic (`lib/money.ts`, the invoice form's running total), and that arithmetic must mirror
the server's rounding rule (round each line, then sum) or the two will disagree by a cent on
certain inputs. The server's value is always authoritative; a client-computed total is a preview.

---

## Errors

`ProtectedError` (deleting a row something else references via `on_delete=PROTECT`) is caught
globally by `config.exceptions.api_exception_handler` and turned into **400 with a readable
message** — e.g. `"Cannot delete this record because it is referenced by 2 invoices."` — never an
unhandled 500. Any new `PROTECT` relationship is covered by this automatically; don't add
per-viewset handling for it.

DRF's two error shapes (`{"detail": "..."}` for auth/permission failures, `{"field": ["..."]}`
for validation) are both surfaced verbatim by the frontend's `ApiError` — don't re-wrap or
paraphrase them in the UI.

---

## Permissions and scoping

One `RolePermission` class covers both axes at once — read/write and ownership — because
splitting them invites one being updated without the other:

| role | list / retrieve | create | update / delete |
|---|---|---|---|
| `ADMIN` | all | yes | any |
| `STAFF` | own only | yes | own only |
| `VIEWER` | all | no | no |

- `STAFF` scoping is applied via `scope_to_role()`, a plain function both the viewset mixin and
  the (non-viewset) dashboard `APIView` call — the STAFF filter exists in exactly one place.
- `created_by` is set from `request.user` in `perform_create()`, **never** accepted from the
  request body. `role` is writable only through `/api/users/`, by an `ADMIN` — a user can never
  escalate themselves.
- A `STAFF` user reaching another owner's row gets **404, not 403**. This is deliberate: a 403
  would confirm the row exists. Any serializer field that references a scoped model *and* is
  writable (e.g. `Transaction.invoice` on the standalone endpoint) must validate ownership itself
  — the queryset-narrowing mixin only protects reads.

---

## No test suite

A deliberate choice, not an oversight — see `architecture.md`'s decision log for the tradeoff.
Verification instead means, in order: `manage.py check`, `makemigrations --check --dry-run`, a
`manage.py shell` session exercising the actual behavior, and `curl` against a running server for
anything that crosses the API boundary. `docs/specs/` entries must each name their own
verification steps up front, given this constraint — see the spec template.

---

## Design tokens

Never hand-tune a value in `frontend/src/styles/tokens.css` directly — it's a verbatim port of
the imported design system. Change the source design system and re-port. See `design-tokens.md`
for the hard rules (gradient-as-rule-only, amber cap, pill buttons) and the audit command that
catches violations.
