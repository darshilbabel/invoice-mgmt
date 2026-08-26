# Eval run — three degraded invoice PDFs

Hand-written analysis of the run below. Regenerate the mechanical half with:

```bash
source .venv/bin/activate && cd backend
python -m evals.report \
  100_poor_crop_right 101_poor_crop_corner 113_augraphy_scan_lines \
  --judge-repeats 5 --extract-samples 8 \
  --preamble evals/reports/2026-08-25-negative-crop.preamble.md \
  -o evals/reports/2026-08-25-negative-crop.md
```

## What was run, and against what

Three files from `~/Downloads/Sample_Invoices/negative/`:

| PDF | Degradation | What survives on the page |
|---|---|---|
| `100_poor_crop_right.pdf` | Right edge cropped away | Everything except the invoice number's last digit, the year's final `4`, and the Amount Due row's last `0`. The TOTAL row, Qty, Rate and the line Amount are intact. |
| `101_poor_crop_corner.pdf` | Thin bevel off the corners | Everything. Fully legible at 300 DPI — the control. |
| `113_augraphy_scan_lines.pdf` | Scan-lines pass over the whole page | Almost nothing. Every dark glyph is reduced to one narrow vertical stripe. Only the green logo and the white-on-black table header band survive. |

All three are degraded renderings of one source document, also in that folder
undegraded: `775251047-Kentucky-Dental-invoice.pdf` — Northern Kentucky Dental care
→ Kimberly Carius, invoice `00321706`, one line at `1 × 1260.00`, total `$1,260.00`.
Every golden was written against that original and then checked field by field
against the degraded page at 300 DPI. None of the three has a text layer, so all of
this exercises the vision path end to end.

### The golden convention, because it decides several fields

A golden records **what is legible on its own page**, not what the undamaged
original says. `100_poor_crop_right`'s invoice number is therefore `0032170`, not
`00321706` — the extractor cannot see a digit the crop deleted. `113`'s golden
declares a **refusal** as the correct outcome, and fills `issuer.name` from the logo
because that is the one thing on the page anyone can still read.

## The headline

**The two crop fixtures pass everything — 13/13 each.** All eight deterministic
metrics, tool correctness, and all four judged metrics, the last stable across five
samples. The right-edge crop caused no misread total, no wrong party, no invented
field.

**`113` is a different story, and it is the finding of this run.** Sampled eight
times, the extractor refused five and **fabricated a complete invoice three times**
— see finding 1. Its single cached extraction happened to be a refusal, so on the
first pass it scored a clean 3/3. It was the sampling, not the fixture, that
found this.

## Finding 1 — it invents invoices from unreadable pages, about 4 runs in 10

On a page where no digit, no date, no invoice number and neither party's name can
be read by anyone, the extractor sometimes returns a complete, confident invoice.
Across twelve live calls against the same PDF it refused seven times and extracted
five. The extractions do not agree with each other, which is what confirms they are
invented rather than read:

| Run | Customer returned | Total returned | Line item | Flagged low-confidence |
|---|---|---|---|---|
| a | `John Doe` | `85.00` | 1 row | — |
| b | — | `100.00` | `Initial consultation` | issue/due date, invoice no., description, unit price |
| c | `Jane Doe` | `100.00` | `Dental Cleaning` | issue/due date, printed total, qty, unit price |
| d | `Joseph M. Brown` | `150.00` | `Dental Cleaning` | **description only** |

Nothing in that table is on the document. The real customer is Kimberly Carius, the
real total is `1260.00`, the real line is `Dental Examination  A Prescription has
been written out to the patient…`, and run **d** additionally invented both dates
(`2025-10-01`, `2025-11-01`) and an invoice number (`000081112840`).

**Run d is the one to look at.** It flagged only the line description. So the
customer, the invoice number, both dates and the total would arrive at
`/invoices/upload/review` with no amber marker on them — presented to the reviewer
as values read off the page. That is precisely the failure `docs/design-tokens.md`
reserves amber for, and the one `ConfidenceCalibration` exists to catch.

**Why it matters more than a wrong number.** `POST /api/invoices/extract/` resolves
the extracted supplier to a `Customer`, **creating the row when nothing matches**
(`docs/domain.md`, and `docs/specs/2026-08-ocr-ingest.md` open question 4). Three
different fictional people in eight runs is three permanent `Customer` rows, and
`Customer` is `on_delete=PROTECT` — once an invoice references one it cannot be
deleted.

**Suggested direction, not applied here.** The model is being asked to judge
legibility and to extract in the same breath, and the `has_content` rule is the only
thing standing between an unreadable page and an invented invoice. Worth trying a
sharper instruction — refuse when the *values* cannot be read, not only when the
page is blank — and re-measuring with `--extract-samples`. That is a prompt change,
so it needs a decision and a re-baseline, not a quiet edit.

## Finding 2 — the harness sampled the extractor once and cached it

The suite has always extracted each fixture once and scored that sample. For a
legible invoice that is right and it is what keeps the suite affordable. For a page
at the edge of readability it means the verdict is whichever answer landed in the
cache first. `113` scored 3/3 PASS that way.

This is the same mistake the judge rubrics made one layer down: judged metrics were
already sampled five times *because* `claude-sonnet-5` cannot be pinned to greedy
decoding — and the extractor, which cannot be pinned either, was sampled once.

`evals/stability.py` and the `Refuses every time` metric close it. Samples
accumulate in the cache, so raising `--extract-samples` tops up rather than
re-billing. It is applied only to fixtures whose golden declares `expect_error`,
where "does it refuse" is the whole question.

## Finding 3 — the judged rubrics were written on the wrong scale. Fixed.

GEval asks its judge for a score on a **0–10** scale and divides by ten. The rubrics
in `evals/metrics/judged.py` were written in 0.0–1.0 language — *"Score 1.0 if they
name the same billable item."* So "the same item" had two defensible answers, `10`
and `1`, and `1/10 = 0.10` sits below every threshold in the suite. A correct
extraction failed about half the time, carrying a written reason saying the two
texts were identical.

| Judged metric | Samples before | Samples after |
|---|---|---|
| Line description equivalence | `0.10, 1.00, 1.00, 0.10, 0.10` — **unstable** | `1.00 ×5` on both crop fixtures |
| Customer identity | `1.00 ×5` (latently exposed) | `1.00 ×5` |
| Notes grounding | `1.00 ×5` (latently exposed) | `1.00 ×5` |

All three rubrics now say "award the maximum score" / "award the minimum score" and
name no numbers. Thresholds, criteria and the judge are unchanged.
`customer_identity` also changed *meaning*: its "score around 0.5" middle case read
as `0.05`, below its own threshold, so a right-company-wrong-address match scored
the same as a different company entirely.

**This moves the baseline.** Any judged score recorded before 2026-08-25 was taken
under the old wording and is not comparable with what follows.

## Finding 4 — two error messages that blame the wrong thing

Both minor next to finding 1, both user-facing, neither fixed here — they are
application code, not evals.

- A misconfigured `OPENAI_MODEL` reaches the user as *"your PDF could not be read"*.
  `extraction.py` maps every `BadRequestError` to `NOT_PDF`, so a bad model name
  takes the same branch as a corrupt upload. Hit during this work when the default
  briefly pointed at a model that does not exist.
- `113`'s refusal says *"The pages may be images with no text layer, or this may not
  be an invoice."* Neither is true. It is plainly an invoice, plainly from this
  supplier — what is unreadable is every value on it. The refusal is right; the
  sentence sends the user looking for the wrong problem.

## How to read the metric families below

| Family | Cost | What a failure means |
|---|---|---|
| **Deterministic** (8 metrics) | Free | A real extraction defect on a fixture that returned a payload: wrong money, wrong party, a missed or invented row, a flag pointing at nothing. Compared with `==` on strings — no model is consulted about a number or a date. |
| **Rejection** (3 metrics) | 1 free, 1 billable | Only for a fixture whose correct outcome is a refusal. `Refused, with the right reason` and `Nothing fabricated` score the cached extraction; `Refuses every time` scores eight live ones, and is the only metric in the suite that can see a nondeterministic failure. |
| **Tool correctness** (1 metric) | Free | The pipeline did not take the whole path. Stages are recorded live by `evals/trace.py` wrapping the names `billing/extraction.py` actually calls, so a stage appears because it ran, never because the payload implied it. This is what distinguishes *refused before the model was called* from *the model looked and said there is no invoice here* — `113` is the first fixture to demonstrate the second, on a real document. |
| **Judged** + **Answer relevancy** (4 metrics) | Billable, `claude-sonnet-5` | Either a real semantic mismatch or judge noise. Every judged metric is measured 5× and reports the **median**, with all samples in the "Repeat runs" column. Treat any row marked **unstable** as no verdict at all — that column is what made finding 3 visible. |

Note the metric counts differ by fixture, and a `3/4` is not a weaker result than a
`13/13` — a refusal fixture has no payload for the other ten metrics to score.

## The one coverage gap left

**No fixture is `rounding_divergent`.** This invoice is a single line of
`1 × 1260.00`, where round-each-then-sum and sum-then-round agree, so
`metrics/totals.py` passes without ever demonstrating the rule it exists to protect.
Closing it needs an invoice with fractional cents — `docs/domain.md`'s own example
is three lines of `0.25 × 0.50`. The `expect_error` gap that stood beside it is now
closed by `113`.

---

# Extraction eval — negative (degraded) invoice PDFs

Run 2026-08-25 12:11 UTC · extractor `billing/extraction.py` · judge `claude-sonnet-5 (Anthropic)`

Judged metrics were measured 5x each and report the median; `claude-sonnet-5` cannot be pinned to greedy decoding, so a single sample is not a verdict. See evals/judge.py.

| PDF | Passed | Failed metrics |
|---|---|---|
| `100_poor_crop_right.pdf` | 13/13 | none |
| `101_poor_crop_corner.pdf` | 13/13 | none |
| `113_augraphy_scan_lines.pdf` | 3/4 | Refuses every time |

## `100_poor_crop_right.pdf`

- **Fixture** — `100_poor_crop_right`, 1 page, golden `100_poor_crop_right.expected.json`
- **Extraction** — served from cache, 4.8s, payload returned
- **Result** — **13/13 metrics passed**

| Family | Metric | Score | Threshold | Verdict | Repeat runs |
|---|---|---|---|---|---|
| Deterministic | Bill-to, not issuer | 1.00 | 1.00 | PASS | — |
| Deterministic | Line items - numerics | 1.00 | 1.00 | PASS | — |
| Deterministic | No summary rows | 1.00 | 1.00 | PASS | — |
| Deterministic | Total reconciliation | 1.00 | 1.00 | PASS | — |
| Deterministic | Line items - fidelity | 1.00 | 0.90 | PASS | — |
| Deterministic | Scalar fields | 1.00 | 0.90 | PASS | — |
| Deterministic | Confidence calibration | 1.00 | 0.80 | PASS | — |
| Deterministic | low_confidence paths resolve | 1.00 | 1.00 | PASS | — |
| Tool correctness | Pipeline stages called | 1.00 | 1.00 | PASS | — |
| Judged | Line description equivalence (row 0) | 1.00 | 0.70 | PASS | stable (1.00, 1.00, 1.00, 1.00, 1.00) |
| Judged | Customer identity | 1.00 | 0.70 | PASS | stable (1.00, 1.00, 1.00, 1.00, 1.00) |
| Judged | Notes grounding | 1.00 | 0.70 | PASS | stable (1.00, 1.00, 1.00, 1.00, 1.00) |
| Answer relevancy | Answer relevancy | 0.92 | 0.70 | PASS | stable (1.00, 0.92, 0.92, 0.92, 0.92) |

### Why each metric scored what it did

**Bill-to, not issuer** — PASS (1.00)  
returned 'Kimberly Carius', which is not the issuer ('Northern Kentucky Dental care')

**Line items - numerics** — PASS (1.00)  
all 1 matched rows have exactly the right quantity and unit price

**No summary rows** — PASS (1.00)  
no subtotal, tax or total row was imported as a line item

**Total reconciliation** — PASS (1.00)  
line items total 1260.00, matching the page

**Line items - fidelity** — PASS (1.00)  
1/1 rows found, 1 returned (recall 100%, precision 100%)

**Scalar fields** — PASS (1.00)  
all 4 scalar fields correct

**Confidence calibration** — PASS (1.00)  
recall 100%, precision 100%. nothing was both misread and marked ambiguous in the fixture, so recall has no denominator on this invoice

**low_confidence paths resolve** — PASS (1.00)  
nothing was flagged, so no paths to resolve

**Pipeline stages called** — PASS (1.00)  
[ Tool Calling Reason: Correct ordering: all expected tools ['encode_pdf_base64', 'openai_responses_create', 'parse_structured_output', 'normalise_payload'] were called in the correct order. Tool Selection Reason: No available tools were provided to assess tool selection criteria ] | expected ['encode_pdf_base64', 'openai_responses_create', 'parse_structured_output', 'normalise_payload'] | called ['encode_pdf_base64', 'openai_responses_create', 'parse_structured_output', 'normalise_payload']

**Line description equivalence (row 0)** — PASS (1.00)  
The two texts describe the identical billable item: a Dental Examination with a prescription noted for denture repair and relining services. The only differences are capitalization ('A' vs 'a') and minor spacing, which do not change the billed item per the evaluation criteria. This matches the rule that reordering, punctuation, and capitalization differences should be treated as the same item.

**Customer identity** — PASS (1.00)  
The actual output and expected output are identical in both the name (Kimberly Carius) and the full postal address (29 Brumble Avenue, Highland Heights, KY 41076, U.S.A). Since they refer to the same real-world party at the exact same address, this meets the criteria for the maximum score.

**Notes grounding** — PASS (1.00)  
The actual output states 'It was great doing business with you,' which matches verbatim the Notes section in the expected printed text. No invented payment terms, bank details, or dates are present. The statement is fully supported by the printed invoice text, warranting the maximum score.

**Answer relevancy** — PASS (0.92)  
The score is 1.00 because the actual output directly addresses every element requested in the input, including the billing party, invoice number, issue and due dates, line items with descriptions, quantities and unit prices, the total, and any fields of uncertainty, with no irrelevant statements present.

### Recorded pipeline trace

| # | Stage | Detail |
|---|---|---|
| 1 | `encode_pdf_base64` | pdf_bytes=141324 |
| 2 | `openai_responses_create` | model=gpt-4o, response_format=json_schema, seconds=4.64 |
| 3 | `parse_structured_output` | characters=570 |
| 4 | `normalise_payload` | model_flags=0, rows=1 |

<details><summary>Extracted payload</summary>

```json
{
  "customer_guess": {
    "billing_address": "29 Brumble Avenue\nHighland Heights, KY 41076\nU.S.A",
    "email": "",
    "name": "Kimberly Carius"
  },
  "due_date": null,
  "field_notes": {},
  "issue_date": "2024-07-05",
  "low_confidence": [],
  "notes": "It was great doing business with you.",
  "page_count": 1,
  "printed_total": "1260.00",
  "source_invoice_number": "0032170",
  "transactions": [
    {
      "description": "Dental Examination A prescription has been written out to the patient for denture repair and relining services",
      "quantity": "1.00",
      "unit_price": "1260.00"
    }
  ]
}
```

</details>

---

## `101_poor_crop_corner.pdf`

- **Fixture** — `101_poor_crop_corner`, 1 page, golden `101_poor_crop_corner.expected.json`
- **Extraction** — served from cache, 3.1s, payload returned
- **Result** — **13/13 metrics passed**

| Family | Metric | Score | Threshold | Verdict | Repeat runs |
|---|---|---|---|---|---|
| Deterministic | Bill-to, not issuer | 1.00 | 1.00 | PASS | — |
| Deterministic | Line items - numerics | 1.00 | 1.00 | PASS | — |
| Deterministic | No summary rows | 1.00 | 1.00 | PASS | — |
| Deterministic | Total reconciliation | 1.00 | 1.00 | PASS | — |
| Deterministic | Line items - fidelity | 1.00 | 0.90 | PASS | — |
| Deterministic | Scalar fields | 1.00 | 0.90 | PASS | — |
| Deterministic | Confidence calibration | 1.00 | 0.80 | PASS | — |
| Deterministic | low_confidence paths resolve | 1.00 | 1.00 | PASS | — |
| Tool correctness | Pipeline stages called | 1.00 | 1.00 | PASS | — |
| Judged | Line description equivalence (row 0) | 1.00 | 0.70 | PASS | stable (1.00, 1.00, 1.00, 1.00, 1.00) |
| Judged | Customer identity | 1.00 | 0.70 | PASS | stable (1.00, 1.00, 1.00, 1.00, 1.00) |
| Judged | Notes grounding | 1.00 | 0.70 | PASS | stable (1.00, 1.00, 1.00, 1.00, 1.00) |
| Answer relevancy | Answer relevancy | 0.92 | 0.70 | PASS | stable (0.92, 0.85, 0.83, 0.92, 1.00) |

### Why each metric scored what it did

**Bill-to, not issuer** — PASS (1.00)  
returned 'Kimberly Carius', which is not the issuer ('Northern Kentucky Dental care')

**Line items - numerics** — PASS (1.00)  
all 1 matched rows have exactly the right quantity and unit price

**No summary rows** — PASS (1.00)  
no subtotal, tax or total row was imported as a line item

**Total reconciliation** — PASS (1.00)  
line items total 1260.00, matching the page

**Line items - fidelity** — PASS (1.00)  
1/1 rows found, 1 returned (recall 100%, precision 100%)

**Scalar fields** — PASS (1.00)  
all 4 scalar fields correct

**Confidence calibration** — PASS (1.00)  
recall 100%, precision 100%. nothing was both misread and marked ambiguous in the fixture, so recall has no denominator on this invoice

**low_confidence paths resolve** — PASS (1.00)  
nothing was flagged, so no paths to resolve

**Pipeline stages called** — PASS (1.00)  
[ Tool Calling Reason: Correct ordering: all expected tools ['encode_pdf_base64', 'openai_responses_create', 'parse_structured_output', 'normalise_payload'] were called in the correct order. Tool Selection Reason: No available tools were provided to assess tool selection criteria ] | expected ['encode_pdf_base64', 'openai_responses_create', 'parse_structured_output', 'normalise_payload'] | called ['encode_pdf_base64', 'openai_responses_create', 'parse_structured_output', 'normalise_payload']

**Line description equivalence (row 0)** — PASS (1.00)  
The two texts describe the identical billable item—a dental examination with a prescription note for denture repair and relining services. The only difference is a minor whitespace variation (double space) between words, which does not change the billed item at all. This aligns with maximum score criteria since the wording, order, and content are essentially identical.

**Customer identity** — PASS (1.00)  
The actual output and expected output are identical in both name and address details, referring to the same individual/organisation at the same address. This meets the criteria for maximum score.

**Notes grounding** — PASS (1.00)  
The actual output 'It was great doing business with you.' appears verbatim in the expected printed text under the Notes section. No invented content, dates, payment terms, or bank details are introduced. This fully satisfies the criteria for maximum score.

**Answer relevancy** — PASS (0.92)  
The score is 0.92 because the output correctly addresses nearly all requested invoice fields, but it includes an irrelevant mention of a prescription for denture repair, which is not part of the requested information and adds extraneous content unrelated to the invoice fields asked about.

### Recorded pipeline trace

| # | Stage | Detail |
|---|---|---|
| 1 | `encode_pdf_base64` | pdf_bytes=141712 |
| 2 | `openai_responses_create` | model=gpt-4o, response_format=json_schema, seconds=3.1 |
| 3 | `parse_structured_output` | characters=532 |
| 4 | `normalise_payload` | model_flags=0, rows=1 |

<details><summary>Extracted payload</summary>

```json
{
  "customer_guess": {
    "billing_address": "29 Brumble Avenue\nHighland Heights, KY 41076\nU.S.A",
    "email": "",
    "name": "Kimberly Carius"
  },
  "due_date": null,
  "field_notes": {},
  "issue_date": "2024-07-05",
  "low_confidence": [],
  "notes": "It was great doing business with you.",
  "page_count": 1,
  "printed_total": "1260.00",
  "source_invoice_number": "00321706",
  "transactions": [
    {
      "description": "Dental Examination A Prescription has been written out to the patient for denture repair and relining services",
      "quantity": "1.00",
      "unit_price": "1260.00"
    }
  ]
}
```

</details>

---

## `113_augraphy_scan_lines.pdf`

- **Fixture** — `113_augraphy_scan_lines`, 1 page, golden `113_augraphy_scan_lines.expected.json`
- **Extraction** — served from cache, 3.1s, refused - no_text (a refusal is the golden's expected outcome)
- **Result** — **3/4 metrics passed**

| Family | Metric | Score | Threshold | Verdict | Repeat runs |
|---|---|---|---|---|---|
| Rejection | Refuses every time | 0.62 | 1.00 | FAIL | — |
| Rejection | Nothing fabricated | 1.00 | 1.00 | PASS | — |
| Rejection | Refused, with the right reason | 1.00 | 1.00 | PASS | — |
| Tool correctness | Pipeline stages called | 1.00 | 1.00 | PASS | — |

### Why each metric scored what it did

**Refuses every time** — FAIL (0.62)  
FABRICATED an invoice on 3 of 8 runs of the same page. invented customers: 'Jane Doe', 'Joseph M. Brown' — _resolve_customer creates each as a permanent Customer row. invented totals: 100.00, 150.00. 2 of those carried no low_confidence flag on the total, so the review screen would show them as read off the page

**Nothing fabricated** — PASS (1.00)  
nothing came back at all, so nothing could be invented

**Refused, with the right reason** — PASS (1.00)  
refused with 'no_text', as the golden declares

**Pipeline stages called** — PASS (1.00)  
[ Tool Calling Reason: Correct ordering: all expected tools ['encode_pdf_base64', 'openai_responses_create', 'parse_structured_output', 'raise_extraction_error'] were called in the correct order. Tool Selection Reason: No available tools were provided to assess tool selection criteria ] | expected ['encode_pdf_base64', 'openai_responses_create', 'parse_structured_output', 'raise_extraction_error'] | called ['encode_pdf_base64', 'openai_responses_create', 'parse_structured_output', 'raise_extraction_error']

### Recorded pipeline trace

| # | Stage | Detail |
|---|---|---|
| 1 | `encode_pdf_base64` | pdf_bytes=93869 |
| 2 | `openai_responses_create` | model=gpt-4o, response_format=json_schema, seconds=2.89 |
| 3 | `parse_structured_output` | characters=228 |
| 4 | `raise_extraction_error` | reason=no_text |

<details><summary>Extracted payload</summary>

```json
{}
```

</details>
