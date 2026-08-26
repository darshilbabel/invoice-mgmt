# Fixtures

One PDF, one `<name>.expected.json` beside it. That pair is the entire interface.

**PDFs are gitignored; goldens are committed.** A real invoice carries a company
name, a postal address, an email and a set of amounts — putting that in git history
permanently should be a decision someone makes per document, not the default. If you
do want one committed: `git add -f evals/fixtures/that-one.pdf`.

The consequence is that a fresh clone has goldens with no documents beside them.
`dataset.py` says so by name rather than quietly scoring less.

## Adding one

```bash
cd backend
python -m evals.scaffold ~/Downloads/acme-march-2026.pdf
```

Then open the draft and **read the PDF alongside it**. Everything in the draft came
from the extractor, which is the thing being measured — correcting it is the work,
not a formality.

```jsonc
{
  "_verified": false,          // set true only after you have read the PDF
  "source_pdf": "acme-march-2026.pdf",
  "page_count": 2,

  // Off the letterhead. The scaffold leaves these null on purpose: it is the one
  // field that proves the extractor picked the right party, so the extractor is
  // not allowed to supply it. The loader refuses the fixture until it is filled.
  "issuer":  { "name": null, "email": null, "address": null },

  // The party the invoice is addressed to — "Bill to", "Invoice to", "Sold to".
  "bill_to": { "name": "Northwind Traders",
               "email": "ap@northwind.example",
               "address": "12 Harbour Rd, Mumbai 400001" },
  "customer_absent": false,    // true when the page addresses nobody at all

  "source_invoice_number": "INV-2026-0031",
  "issue_date": "2026-03-04",  // ISO, always
  "due_date": null,

  "printed_total": "70800.00", // the number printed on the page, not a computed one
  "printed_total_absent": false,  // true when no total is printed at all

  // One entry per row of the table. Money is a 2dp string, always.
  "line_items": [
    { "description": "Design retainer, March", "quantity": "1.00", "unit_price": "60000.00" }
  ],

  // The invoice's own summary rows, exactly as printed. These must never come
  // back as line items — importing one roughly doubles the invoice.
  "forbidden_descriptions": ["Subtotal", "GST 18%", "Grand total"],

  // Fields a careful reader would ALSO hesitate over, and why. This is what makes
  // calibration measurable: a field the extractor got wrong that was perfectly
  // legible should have been right, not flagged.
  "ambiguous": {
    "due_date": "Printed 07/03 — could be 7 March or 3 July."
  },

  // Text printed outside the line-item table, for the notes-grounding judge.
  "notes_source_text": "Payment within 15 days. Bank details overleaf.",

  "rounding_divergent": false, // computed by the scaffold; do not hand-edit
  "expect_error": null         // e.g. {"reason": "no_text"} for a non-invoice
}
```

## What a good fixture set covers

The loader warns when the set cannot prove something. Aim for:

- **an invoice with fractional cents** — line totals where round-each-then-sum and
  sum-then-round disagree (`docs/domain.md`'s example is three lines of `0.25 × 0.50`).
  Without one, the rounding metric cannot demonstrate the rule it protects.
- **something genuinely hard to read** — a day-first/month-first date, a struck-through
  quantity, a smudge — recorded in `ambiguous`. Without one, calibration has an empty
  recall denominator on every case.
- **a multi-page invoice**, so `page_count` means something.
- **a non-invoice document** with `expect_error`, so the rejection path is exercised
  by a real file rather than synthetic bytes.
- **an invoice addressing no party**, with `customer_absent: true`, if you have one.
  The prompt says return null rather than falling back to the issuer, and that branch
  is otherwise untested.
