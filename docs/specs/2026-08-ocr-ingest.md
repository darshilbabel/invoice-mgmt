# OCR invoice ingest

**Status: implemented, end to end.**

`POST /api/invoices/extract/` reads an uploaded PDF with OpenAI and returns fields for review.
`/invoices/upload` and `/invoices/upload/review` (wireframe turn 3, `3a`–`3d`) present them, and
the review screen's Save is the ordinary `POST /api/invoices/`. Every open question below is
closed.

**One rule in this document was reversed on the way there** — extraction now creates a `Customer`
when the supplier matches nothing on file. It is marked **[reversed]** at open question 4 with the
cost stated, rather than quietly dropped.

## Problem

Every invoice today is entered by hand: customer, dates, and each line item typed into the form
at `/invoices/new`. For a paper or PDF invoice a client has already sent, that's pure
transcription — and transcription of money is exactly where typos are expensive.

## Goal

Let a user upload a PDF invoice and review what was extracted — customer, dates, line items —
correcting rather than typing from scratch. The user always has the last word before anything
saves.

> **Revised.** This section originally said the extraction would pre-fill the existing
> `/invoices/new` form, with no new route. The wireframes drew a dedicated flow instead, and that
> is what was built: a chooser at `/invoices/upload` and a review screen at
> `/invoices/upload/review`. The review screen carries affordances the shared form has no place
> for — per-field confidence markers, a customer match/create card, the source-file panel, and a
> cross-check of the PDF's printed total against the sum of the extracted rows. `InvoiceForm` is
> untouched; the two screens share `lib/money.ts` and nothing else.

## Scope

- Single-file upload, PDF only, reached from `Upload PDF` beside `New invoice` on the invoice list.
- Extraction feeds a **review screen**, not the create form — but it produces no new save path and
  no new API contract for creating an invoice. What the review screen builds is the same
  `customer / issue_date / due_date / transactions[]` shape `InvoiceForm` already sends
  (`docs/architecture.md` § Invoice write shape), so saving is the existing `POST /api/invoices/`.
- The extracted `customer` is a **suggestion**: since `Customer` is a real FK
  (`domain.md`), extraction can propose a name/email but the user picks (or creates) the actual
  `Customer` row — extraction never creates a `Customer` implicitly.

## Non-goals

- No batch upload, no auto-save, no "trust the extraction" fast path. A human reviews every
  field before POST.
- No change to `Invoice`, `Transaction`, or the write shape. Extraction is a pre-fill mechanism
  in front of the existing form, not a new persistence path.
- No OCR of the *stored* invoice PDF for anything else (search, audit) — out of scope here.

## Proposed data flow

```
user selects file on /invoices/new
        │
        ▼
POST /api/invoices/extract/   (new endpoint, ADMIN + STAFF only — matches invoice-create permission)
  multipart: file
        │
        ▼
  synchronous extraction (see open questions — engine undecided)
        │
        ▼
  200 { source_invoice_number, issue_date, due_date, notes,
        customer_guess: {name, email, billing_address},
        transactions: [{description, quantity, unit_price}, ...],
        printed_total,                       // cross-check only, never stored
        low_confidence: ["due_date", "transactions.2.quantity"],
        field_notes: {...}, page_count }
        │
        ▼
  /invoices/upload/review fills itself from the response.
  Nothing is persisted. The user edits and clicks "Save invoice", which is the
  ordinary POST /api/invoices/ — exactly the request the create form sends today.
```

No new model. No new table. The response is `InvoiceInput` (`frontend/src/types.ts`) minus
`customer` — extraction can only ever return a *name and email* to search `/api/customers/` with,
since it has no way to know the row's PK — plus the review-screen extras: which fields to flag,
how many pages, and what total the PDF itself printed. The TypeScript mirror of all of it is the
`ExtractionResult` block at the bottom of `types.ts`; it is the one part of that file with nothing
on the other side yet.

## Constraints inherited from the existing codebase

- **Money must still end up as a 2dp string** (`conventions.md` § Money) — whatever the OCR
  engine returns for prices needs normalizing before it reaches the review screen's state, the
  same way `lib/money.ts` handles it today.
- **No stored total, ever** (`domain.md`). The review screen's own total is `sumLines()` over its
  rows and nothing else. `printed_total` exists only to be *compared* against that, and is never
  saved, sent, or shown as the invoice's total — see open question 7.
- **This app has no test suite** (`conventions.md`). Whatever ships here needs the same kind of
  hand-verification discipline as everything else — see Verification below.
- **No new dependency without approval** (`conventions.md` § Dependencies). This is the
  constraint that most affects this spec: there is currently no OCR/PDF-parsing library
  anywhere in `requirements.txt`, and every plausible option is a new one. That approval gate is
  the first open question, not an implementation detail.

## Open questions

### Closed — the backend decisions

1. **Extraction engine** — *OpenAI, via the `openai` SDK.* Approved 2026-08-24 and added to
   `requirements.txt`; the only dependency this feature has. The PDF is sent **as a file**,
   base64-inline, not as extracted text — which means a scanned, image-only invoice is read by
   vision rather than failing, so no OCR library is needed here or ever. Configured by
   `OPENAI_MODEL` / `OPENAI_TIMEOUT_SECONDS`; the key is required at startup with no default, like
   `SECRET_KEY`.

   Consequences accepted: invoice data leaves the server, each upload costs money, and the request
   blocks for the whole call because there is no job queue. `billing/extraction.py` is the only
   file that knows any of this — it imports no ORM, so replacing the engine is one file.
2. **File storage** — *discarded.* Read into memory, sent, dropped. No `MEDIA_ROOT`, no
   `FileField`, no migration, and nothing left in OpenAI's file storage either. The cost is that
   there is no audit trail from a saved invoice back to the document it came from. Revisit by
   adding `Invoice.source_file` and a media decision, not by changing the extraction path.

### Closed — the UI decisions

3. **Low-confidence handling** — *fill the field, and mark it.* Never blank, never refused: a
   value the user can correct beats a gap they have to source themselves. The extractor returns
   `low_confidence` as a list of field paths plus an optional `field_notes` explanation
   ("Read as 20/07 — could be 20 July or 7 December"). The marker is amber, the one place this app
   uses the accent (`docs/design-tokens.md`), and it clears as soon as the user edits the field —
   so the "3 fields need a look" counter means something.
4. **Customer matching** — **[reversed]** *the backend matches, and creates the row when nothing
   matches.* `_resolve_customer()` in `billing/views.py` tries `email__iexact`, then the printed
   name against both `name` and `company_name`; on no match it creates a `Customer` and returns it
   with `customer_created: true`, which the review screen surfaces as a **Created** badge and a
   line of copy saying so. A picker is always available to override it.

   This reverses what *Scope* above says ("extraction never creates a `Customer` implicitly — the
   user picks"). The Scope bullet is left standing as the record of the original intent. **The
   cost is real and worth stating: upload a PDF, glance at it, hit Discard — and a customer row
   for a possibly-misread supplier name is already in the database, permanently, because
   `Customer` is `on_delete=PROTECT` and can only be removed by hand from `/customers`.** If that
   churn becomes a problem, moving creation back to an explicit frontend action is a small change
   on both sides: drop the create branch from `_resolve_customer`, return the guess instead, and
   have the review screen POST `/api/customers/` on a button.
5. **File size / type limits** — *10 MB, PDF only, one file at a time, checked on both sides.*
   `INVOICE_UPLOAD_MAX_BYTES` is the real limit; the server also verifies the `%PDF-` magic bytes
   rather than trusting the extension or the client-supplied content type, both of which the
   client chooses. The browser checks the same size first purely to avoid uploading 10 MB just to
   be told no — a courtesy, never the control.

### Raised by the wireframes, and settled

6. **Progress reporting.** `3b` drew "Step 2 of 3" with a percentage and "about 20s remaining".
   That needs a job the client polls. The endpoint here is one blocking call with nothing to
   report mid-flight, so the three named steps were kept but the bar is **indeterminate** and no
   time remaining is claimed. Revisit only if a job model is ever added.
7. **The printed total.** `3c` shows the PDF's own total beside the sum of the extracted rows. The
   extractor therefore returns `printed_total` — but purely as a cross-check, never as a value the
   app stores or displays as authoritative. A disagreement means a row was misread. This does not
   weaken `domain.md`'s rule: the total is still computed from line items, always.
8. **The supplier's invoice number.** `3c` drew it as an editable field. It cannot be:
   `Invoice.invoice_number` is derived from the primary key and has no column. It is shown
   read-only, labelled as printed on the PDF, and discarded on save. If suppliers' numbers need to
   be retained, that is a new field and a separate ticket.

## Verification

There is no test suite (`conventions.md`), and extraction is the part of this codebase least
suited to one anyway: the model's output is not deterministic, so the only real check is a person
reading a PDF alongside what came back. **Re-do this by hand whenever the prompt, the model or the
schema changes** — none of those failures are loud.

### Backend

```bash
python manage.py check
python manage.py makemigrations --check --dry-run   # must report nothing: no model changed

TOKEN=...   # from POST /api/auth/login/
curl -s -H "Authorization: Token $TOKEN" -F file=@sample.pdf \
     http://localhost:8000/api/invoices/extract/ | python -m json.tool
```

Expect the documented shape with **money as quoted strings** — a bare number there means a
`DecimalField` was skipped somewhere. Then the failure paths, none of which may return a 500:
a `.txt` renamed `.pdf` → 400 on the magic-byte check; a file over the limit → 400; an image-only
scan → either a real extraction (vision reads it) or a 400 saying no content was found; a VIEWER's
token → 403; no `Authorization` header → 401.

Also worth one shell session: `billing.extraction.to_money` on `"Rs 6,000.00"`, `"6000"`, `""` and
`"abc"` — the first three are `"6000.00"`, `"6000.00"`, `None`, and the last is `None`, which the
caller turns into a flagged field rather than a silent zero.

### Frontend

`npm run build` is the gate (`tsc -b && vite build`), plus the three greps in
`docs/design-tokens.md`. Then, against a running server, upload a real invoice PDF and check by
hand — nothing else will:

- the extracted line items match the rows on the page, and none of them is a subtotal or tax row
- **the two totals**: the printed one against the sum of the rows. They agreeing is the single
  best signal that nothing was misread; them disagreeing is the whole reason it is on screen
- editing a quantity updates that row, the grand total, and the agreement line together
- an amber marker clears once the field it flags is edited
- the customer says **Matched** or **Created**, and Created really did add the row on `/customers`
- Save lands on the new invoice, whose server-computed total equals what the review screen showed
- reloading `/invoices/upload/review` bounces to the chooser; a VIEWER cannot reach either route
