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
