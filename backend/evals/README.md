# Extraction evals

A scored, repeatable measurement of `billing/extraction.py` — the PDF invoice reader.

`docs/qa-strategy.md` § 4 lists the OpenAI adapter as *"billable and nondeterministic;
rejection paths only, via Newman"*, and `docs/specs/2026-08-ocr-ingest.md` §
Verification says the only real check is *"a person reading a PDF alongside what came
back"*, to be **re-done by hand whenever the prompt, the model or the schema
changes — none of those failures are loud.** This is the automated half of that.

It is **not** a test suite in the sense `docs/conventions.md` § "No test suite" means.
Nothing here proves the extractor correct; the output is not deterministic and never
will be. It produces a score you compare against a previous score.

---

## Running it

```bash
source .venv/bin/activate
cd backend

# The free layers: no judge, no OpenAI beyond one cached call per fixture.
pytest evals/test_contract.py evals/test_failure_modes.py -q

# The scored suite. One OpenAI call per fixture on a cold cache, none on a warm one.
deepeval test run evals/test_extraction_eval.py

# Deterministic metrics only — skips every judge call.
pytest evals/test_extraction_eval.py -m "not judged" -q

# Re-extract deliberately: after changing the model, or to check for drift.
EVAL_REFRESH=1 deepeval test run evals/test_extraction_eval.py
```

With no fixtures, everything collects and skips cleanly. That is deliberate — the
harness should be demonstrably working before the first real invoice arrives, or you
end up debugging two things at once.

---

## Adding a fixture

```bash
cd backend
python -m evals.scaffold ~/Downloads/acme-march-2026.pdf
```

That copies the PDF into `evals/fixtures/`, runs extraction **once**, and writes a
draft `acme-march-2026.expected.json`. Then:

1. **Read the PDF.** Correct every field in the draft against what is actually
   printed. The values came from the extractor, which is the thing being measured.
2. **Fill in `issuer`** — name, email, postal address, off the letterhead. The
   scaffold leaves these null on purpose and the loader refuses the fixture until
   they are filled. See "the guards" below.
3. **Fill in `ambiguous`** — any field a careful reader would also hesitate over, and
   one sentence saying why. This is what makes calibration measurable.
4. **List `forbidden_descriptions`** — the invoice's own Subtotal / Tax / Grand total
   row labels, exactly as printed.
5. **Set `_verified` to `true`.**

Fixture PDFs are gitignored by default: a real invoice carries a company name, a
postal address and amounts, and putting that in git history permanently should be a
decision, not a default. The goldens *are* committed. See `fixtures/.gitignore`.

### The guards, and why they are not paranoia

`dataset.py` refuses to load a fixture — loudly, by filename — when:

| refusal | why |
|---|---|
| `_verified` is still false | A golden copied from the extractor's own output and never checked scores ~1.0 by construction and measures nothing. |
| `issuer.name` is null | It is the one field that proves the extractor picked the right party, so the extractor is not allowed to supply it. |
| `issuer.name == bill_to.name` | An invoice is not addressed to the company that issued it. This means `bill_to` was left as the extractor's guess *and* the extractor confused the parties — the exact failure `direction.py` exists to catch, about to be enshrined as correct. |
| the named PDF is missing | Goldens are committed and PDFs are not, so a fresh clone has one without the other. Better said than silently skipped. |

A refusal is an error, never a skip. A fixture that quietly drops out of a run is
worse than no fixture: the report still says green, over less than it claims.

---

## What is measured

**The dividing rule: numbers and dates are never scored by a model.** A judge that
reasons "6,000 and 6000.00 are basically the same" is precisely the bug this exists
to catch. Money, quantities, dates, counts and set membership are compared exactly.

### Deterministic — no API calls, no cost

| metric | catches | threshold |
|---|---|---|
| **Bill-to, not issuer** | The letterhead returned as the customer. `_resolve_customer` **creates** a `Customer` row from it, and `Customer` is `on_delete=PROTECT` — so this failure writes a permanent row for the supplier's own company. Also checks the subtler half: right company, issuer's email or address. | 1.0 |
| **Line items – numerics** | A misread digit in a quantity or unit price. This is the money bug: `Invoice.total` is computed from these, and there is no stored total to disagree with it. | 1.0 |
| **No summary rows** | A `Subtotal` / `GST 18%` / `Grand total` row imported as a line item, which roughly doubles the invoice. | 1.0 |
| **Total reconciliation** | Three-way: the golden's lines, the extracted lines, and `printed_total`. Also asserts the **per-line-rounded** sum is the one that reconciles — see below. | 1.0 |
| **Line items – fidelity** | Rows missed, invented, merged or split. F1 over a deterministic alignment. | 0.9 |
| **Scalar fields** | Dates, invoice number, printed total, page count — scored **three ways**: correct, wrong, and *fabricated where the page has nothing*. Fabrication scores worst; a plain miss gets partial credit. | 0.9 |
| **Confidence calibration** | Confidently wrong — the failure the amber review marker exists to prevent. Recall weighted 70/30 over precision. | 0.8 |
| **low_confidence paths resolve** | A flagged path naming a field that does not exist, which makes the review screen count "3 fields need a look" and then mark two. | 1.0 |

### Judged — `claude-sonnet-5`, three questions only

Where a string can be right in more than one shape: line-description equivalence
("Homepage design work" vs "Design work — homepage"), customer identity ("Acme Pvt.
Ltd." vs "Acme Private Limited"), and whether `notes` invents anything not on the
page. Each gets one short, single-aspect comparison built from pairs the
deterministic layer already matched — the judge never sees a JSON blob.

---

## Two invariants a future reader will otherwise break

**1. Every judged metric must pass `model=judge()` explicitly.**

deepeval autoloads a dotenv from the working directory. Run from `backend/`, that
supplies `ANTHROPIC_API_KEY` — and also `OPENAI_API_KEY`, because that is what the
application runs on. `initialize_model(None)` checks for an OpenAI key first. So:

```python
GEval(name="...", criteria="...")           # judged by gpt-5.4, on the app's key
GEval(name="...", model=judge(), ...)       # judged by claude-sonnet-5
```

The first one does not fail. It produces scores, fills a report, and bills a key,
and nothing in the output says which model graded the run. Verified — `GEval` must be
constructed in exactly one place, and that place hardcodes the model:

```bash
grep -rn "GEval(" evals --include='*.py' | grep -v "^evals/judge.py"
# expect exactly one hit: `return GEval(` in _geval(), in metrics/judged.py
# (the judge.py hits are prose in its docstring)
```

Every judged metric is constructed through `_geval()`, and `assert_judged_by_sonnet()`
re-checks `metric.evaluation_model` before any run. Do not construct `GEval` anywhere
else.

**2. `DEEPEVAL_MODEL_THINKING` must stay unset.**

`claude-sonnet-5` is registered `supports_thinking=True`, so with that variable set
deepeval sends `thinking={"type": "enabled", "budget_tokens": N}` — and Sonnet 5
removed `budget_tokens`, so the request is a 400. `conftest.py` *pops* it rather than
merely not setting it, because deepeval reads it from that autoloaded dotenv too.

Related: **never run `deepeval set-*`** in this repo. Its settings layer persists
keys by writing to a dotenv file in the working directory — from `backend/`, that is
the application's own.

---

## The rounding rule

`docs/domain.md`'s most-cited rule: rounding each line before summing is not the same
as summing then rounding. Three lines of `0.25 × 0.50` are `0.39` per-line and `0.38`
sum-first.

`evals/money.py` implements **both**, and `metrics/totals.py` computes both and
asserts the per-line figure is the one that reconciles. Computing only the correct
one would leave the suite unable to tell whether it is following the rule or merely
agreeing with itself.

That check is vacuous unless a fixture actually exercises the divergence — on most
invoices the two agree. So `scaffold.py` records `rounding_divergent` per fixture and
`dataset.py` **warns at load** when no fixture has it set. Same for `ambiguous`
(calibration has no recall denominator without it) and `expect_error`. Those warnings
describe what your fixture set cannot currently prove.

---

## Cost, and the cache

Each fixture costs one OpenAI call per run. `runner.py` caches the raw extraction
under `evals/.cache/`, keyed on:

```
sha256(pdf bytes) | OPENAI_MODEL | sha256(PROMPT + canonical SCHEMA)
```

All three components matter. A key of `(pdf, model)` alone would serve a stale answer
after a prompt edit — reporting "no regression" for the exact change most likely to
have caused one. Each cache file records what produced it, so a stale entry can say
so for itself.

Judge calls are not cached. Sonnet 5 does not accept `temperature`, so the judge
cannot be pinned to greedy decoding; caching it would hide its variance, which is the
thing most worth seeing. That is also why the judged rubrics are coarse and their
thresholds have margin.

Note deepeval's own `-c` flag caches *metric* results rather than the extraction
call. The two compose.

---

## Thresholds are provisional

Every threshold in `metrics/__init__.py` is a placeholder except the 1.0s, which are
genuine hard gates. Real numbers come from a baseline over real invoices — a
threshold invented before seeing one is either always green or always red.

The regression check this all exists for: change `OPENAI_MODEL`, or edit `PROMPT`,
re-run, and compare against the last baseline. The cache key notices both by itself.

---

## Layout

```
judge.py       the claude-sonnet-5 judge, built in exactly one place
runner.py      calls extraction; the cache and its key
schema.py      the fixture contract, as pydantic — a typo fails by field name
align.py       two-stage deterministic line matching (never index order, never a judge)
money.py       the rounding rule, mirrored once
dataset.py     fixtures -> test cases, and the guards above
derived.py     single-aspect cases for the judge, from pairs align.py matched
scaffold.py    PDF -> draft golden, with the fields it refuses to fill
metrics/       eight deterministic metrics + the three judged ones
```

Dependencies are pinned in `evals/requirements.txt`, deliberately not in
`backend/requirements.txt` — the application must keep running for someone who has
never installed them. Recorded in `docs/conventions.md` § Dependencies.
