# QA strategy: invoice-mgmt

**Version 1.0** | Last updated: 2026-08-25 | **Owner:** Darshil Babel

> Scope note: this document reverses part of `architecture.md` decision log #2. That reversal is
> deliberate, narrow, and costed in section 4. It is recorded in the decision log itself, not only
> here.

---

### 1. Executive summary

`invoice-mgmt` has better verification than "no test suite" suggests, and worse than production
requires. The Postman/Newman suite — 92 requests, 299 assertions, three seconds — already pins the
API contract, the role matrix, the computed-total rule and the error shapes. What it sits on is
nothing: zero unit tests, zero frontend tests, and **no CI of any kind**, so none of those 299
assertions run unless someone remembers to run them.

Measured against a production bar, the gaps that matter are not coverage gaps. `manage.py check
--deploy` returns **six security warnings** today, `DEBUG` is `True`, `SECRET_KEY` is the
auto-generated insecure one, and there is **no rate limiting anywhere** — `/api/auth/login/` is
`AllowAny` with unlimited attempts. Every uploaded invoice PDF, with the customer's name, billing
address and amounts, is base64-inlined to OpenAI with no data-processing agreement and no
redaction. Five known money- and data-integrity defects are documented and asserted-as-wrong in
the Postman suite.

This strategy therefore sequences hardening first, base-of-pyramid second, defect closure third,
and gates last. It proposes a **scoped reversal** of the no-tests decision — Django's built-in
`TestCase` over money arithmetic and role scoping only, at the cost of **zero new dependencies** —
and promotes the existing Newman suite from a hand-run script to the enforced API gate.

---

### 2. Scope and objectives

**In scope.** The Django + DRF API (`backend/accounts`, `backend/billing`, `backend/config`) and
the React + TypeScript SPA (`frontend/src`). Functional correctness of the money rule and the
role matrix; API contract stability; deployment security configuration; the OpenAI extraction
path's failure modes and its data-handling posture.

**Out of scope, and why.**

| Not covered | Why |
|---|---|
| OpenAI model output quality | Nondeterministic and billable. The human review screen at `/invoices/upload/review` *is* the control; the strategy tests that the review gate cannot be bypassed, not that the model reads well. |
| Cross-browser and mobile | Single-target internal tool. No mobile route exists. Revisit if an external audience appears. |
| Load and performance testing | One-user `runserver` deployment. The blocking 90-second extract is a known architectural limit (section 5), tracked as a risk rather than benchmarked. |
| Visual regression | The design system is ported verbatim and audited by grep (`design-tokens.md`). A screenshot suite would duplicate that at higher maintenance cost. |
| PostgreSQL upgrade path | Django is pinned to 5.2 by PG 14.18. Out of scope here; it is an infrastructure decision, noted in section 12 as a strategy risk. |

**Objectives.**

1. `manage.py check --deploy` returns **0 issues** by end of Phase 1 (week 4). Today: 6.
2. The 299 Newman assertions run on **every push** by end of Phase 1. Today: on request only.
3. The computed-total rule and `scope_to_role()` have regression tests that fail when reverted, by
   end of Phase 2 (week 10). Today: no safety net whatsoever.
4. Documented `KNOWN GAP` defects go **5 to 0** by end of Phase 3 (week 14).
5. All four quality gates enforced in CI by end of Phase 4 (week 20).

---

### 3. Test levels and types

| Level | What it validates | Owner | Framework | Target count | Run frequency |
|---|---|---|---|---|---|
| **Unit** | `line_total` / `total` arithmetic and rounding, `scope_to_role()`, serializer validation, the dashboard aggregate | Developer | **Django `TestCase`** (built in, no new dependency) | ~70 | Every push |
| **API / integration** | Full HTTP contract: auth, role matrix, money-as-strings, error shapes, filtering, pagination, extract rejections | Developer | **Postman + Newman** (`npx`, no install) | 92 requests / 299 assertions | Every push |
| **E2E** | Critical user journeys through both services | Developer | **Playwright MCP** via the repo's `ui-test` skill | 8 journeys, manual | Pre-release + after any UI change |
| **Security config** | Deployment hardening posture | Developer | `manage.py check --deploy` | 0 warnings | Every push |
| **Static** | Type correctness, lint | Developer | `tsc -b` via `npm run build`, `oxlint` | 0 errors | Every push |
| **Migration drift** | Model and migration agree | Developer | `makemigrations --check --dry-run` | Clean | Every push |

Deliberately absent: contract testing (one consumer, one producer, same repo, same commit), load
testing, and visual regression. Each would cost more to maintain than the risk it retires.

**The eight E2E journeys** (manual, scripted as a checklist in the `ui-test` skill):

1. Login with valid credentials; login with invalid credentials shows an error.
2. Create an invoice with multiple line items; the displayed total matches the server's.
3. Edit an invoice, remove a line; the total recomputes.
4. Delete an invoice.
5. STAFF user sees only its own invoices; ADMIN sees all.
6. VIEWER cannot reach any write control.
7. Upload a PDF, review extracted fields, save; the saved invoice matches what was reviewed.
8. Delete a customer that has invoices; a readable 400 appears, not a 500.

---

### 4. Test pyramid analysis

#### Current state

```
Current test distribution:
  Unit tests:         0 count  ->    0 %     (accounts/tests.py, billing/tests.py are stubs)
  Integration/API:   92 count  ->   92 %     (Postman + Newman, 299 assertions)
  E2E tests:          8 count  ->    8 %     (manual, undocumented until now)

Current shape: NO SHAPE - no base at all, a heavy API middle, a manual tip.

CI pipeline duration:  n/a - there is no CI
Flaky test rate:       ~0 % (Newman is deterministic; 99 Teardown restores the baseline)
Test suite pass rate:  100 % (299/299, including 5 tests asserting known-wrong behaviour)
```

The pass rate is the misleading number. It is 100% partly because five of those assertions
**certify defects as correct**. See section 5.

#### Target state

```
Target test distribution:
  Unit (Django TestCase)   ~70  ->  41 %     money + rounding + scope_to_role
  API  (Newman)             92  ->  54 %     already exists; promoted to the gate
  E2E  (Playwright MCP)      8  ->   5 %     manual, the journeys in section 3
                           ----     -----
                            170      100 %

Target CI duration:  < 5 minutes
Target flaky rate:   < 1 %
```

#### This is a diamond, on purpose

The conventional target is 70/20/10. This document targets **41/54/5** and does not apologise for
it. The arithmetic is the argument: holding 92 API tests at 20% of the suite would require roughly
**350 unit tests** over 1,681 lines of non-migration Python. That is a test for every five lines,
most of them asserting that Django works.

The usual case against a diamond is that its middle is mock-heavy, so integration gaps survive
underneath. **That critique does not apply here.** The Newman suite makes real HTTP requests
against a real Django process and a real PostgreSQL database, creating and deleting real rows. It
is not a mock layer; it is the highest-fidelity thing in the repo. Growing the base is worth doing
because unit tests are faster and localise failures better — not because the middle is untrustworthy.

What the base buys, specifically: `Transaction.line_total`'s quantize behaviour and
`scope_to_role()`'s branch cannot be exercised in isolation through HTTP. A Newman test tells you
the dashboard total is wrong; a unit test tells you the rounding is applied outside the `Sum`
instead of inside it.

#### The scoped reversal of decision log #2

Decision log #2 records: *"No automated tests... Consequence: the computed-total rule and the
role-scoping rules in `conventions.md` have no regression safety net."*

The decision is reversed **only for the two rules that sentence names**, and nowhere else.

| | Gets unit tests | Stays as-is |
|---|---|---|
| `billing/models.py` — `line_total`, `total` | yes | |
| `accounts/permissions.py` — `scope_to_role`, `RolePermission` | yes | |
| `billing/views.py` — dashboard aggregate (Round-inside-Sum) | yes | |
| `billing/serializers.py` — validation rules added in Phase 3 | yes | |
| Views, routing, admin registrations, URL wiring | | Newman covers these end to end |
| `billing/extraction.py` — the OpenAI adapter | | Billable and nondeterministic; rejection paths only, via Newman. **Its happy path is now scored, not tested — see § 4.1.** |
| Frontend components | | Manual browser passes |

**The reversal costs zero new dependencies.** `accounts/tests.py` and `billing/tests.py` already
open with `from django.test import TestCase`. Django's built-in runner covers the entire proposed
unit layer. `pytest-django` is explicitly not proposed — it would buy nicer fixtures and cost an
approval under `conventions.md`'s dependency rule.

Two things *would* need approval, and are raised in section 7 rather than assumed:
`coverage` (pip) for line-coverage metrics, and `vitest` (npm) for `frontend/src/lib/money.ts`.

#### 4.1 Extraction: scored, not tested

Added 2026-08-25. `backend/evals/` measures `billing/extraction.py`'s happy path with
**DeepEval**, judged by `claude-sonnet-5`. Dependencies (`deepeval`, `anthropic`) are pinned in
`backend/evals/requirements.txt`, deliberately outside the application's own — recorded in
`conventions.md` § Dependencies.

It is a **fourth kind of thing**, not a fifth test level, and the distinction is the point. Unit,
API and E2E all assert; this one scores. Extraction's output is not deterministic, so nothing here
can pass or fail in the way a `TestCase` does — you compare a run against the previous run. The
row above stands: the adapter still has no *tests*. It now has a baseline.

| | |
|---|---|
| **What it retires** | The instruction in `specs/2026-08-ocr-ingest.md` § Verification to re-read a PDF by hand whenever the prompt, the model or the schema changes. The cache key is those three things, so a run notices all of them by itself. |
| **How it scores** | Eight deterministic metrics (money, party direction, row fidelity, total reconciliation, confidence calibration) plus three judged ones, only for strings that can be right in more than one shape. Numbers and dates are never put to a model. |
| **What it needs** | Real invoice PDFs with hand-verified goldens. The harness ships runnable-but-empty; every fixture is somebody reading a PDF. That is the cost, and it does not go away. |
| **Risks it touches** | "Stray `Customer` rows created by a misread PDF" (§ 5, MED, previously manual-only) is now a hard gate at threshold 1.0. "Money integrity" gains an upstream check: line items are where a wrong total starts. |
| **What it does not do** | Prove correctness, replace journey 7, or run in CI — it spends money per run and should be triggered deliberately, on a model or prompt change. |

---

### 5. Risk assessment

Score = Impact (1 negligible to 5 catastrophic) x Likelihood (1 rare to 5 almost certain).

| Area | Impact | Likelihood | Score | Band | Testing approach |
|---|---|---|---|---|---|
| Deploy hardening: `DEBUG=True`, weak `SECRET_KEY`, no HSTS, insecure cookies | 5 | 4 | **20** | CRIT | `check --deploy` as a blocking CI gate; 0 warnings required |
| PII egress to OpenAI: name, address, amounts, no DPA, no redaction | 4 | 4 | **16** | CRIT | Documented data-flow note; assert the human review gate cannot be bypassed |
| Money integrity: computed total, per-line rounding | 5 | 3 | **15** | CRIT | Unit tests on `line_total`/`total`; Newman cross-check of dashboard vs invoice list |
| Login brute force: no throttling anywhere | 5 | 3 | **15** | CRIT | Add `ScopedRateThrottle`; Newman asserts the 429 |
| Role scoping: cross-owner data leak | 5 | 3 | **15** | CRIT | Unit tests on `scope_to_role`; 18 Newman requests already cover the matrix |
| Blocking 90s extract, no job queue | 3 | 4 | **12** | HIGH | Availability risk, tracked not benchmarked; timeout path asserted |
| `due_date` before `issue_date` accepted, inflating `overdue_count` | 3 | 3 | **9** | MED | Serializer `validate()`; flip the `KNOWN GAP` test |
| Stray `Customer` rows created by a misread PDF | 2 | 4 | **8** | MED | Manual review journey 7; monitor row growth |
| Invoice-number search advertised but non-functional | 2 | 4 | **8** | MED | Fix or remove the placeholder; flip the `KNOWN GAP` test |
| Design-token drift | 2 | 2 | **4** | LOW | The existing grep audit in `design-tokens.md` |

The five CRIT rows are what "production-readiness" means for this codebase, and they set Phase 1's
ordering. Note that the top risk is not a code defect at all — it is configuration, and it is
already detectable by a command that ships with Django.

#### The five `KNOWN GAP` tests

The Postman suite contains five requests prefixed `KNOWN GAP:` that assert the API's *current,
wrong* behaviour. They are green today. **When one goes red, the gap was fixed: update the test,
do not revert the fix.**

1. **A negative `quantity` is accepted.** No validator, no `CheckConstraint`. Compounding it:
   `frontend/src/lib/money.ts` uses `Math.round` (ties toward positive infinity) while the server
   uses `ROUND_HALF_UP` (ties away from zero). For `-0.15 x 0.10` the browser shows `-0.01` and
   the server saves `-0.02`. **`docs/domain.md`'s claim that `money.ts` mirrors the server rule is
   false for negative values.** Closing this defect makes the documentation true.
2. **`due_date` before `issue_date` is accepted** — `InvoiceSerializer` has no `validate()`.
3. **Searching by invoice number finds nothing** — `InvoiceList.tsx` advertises it;
   `search_fields` does not include it, and because `invoice_number` is derived from the primary
   key it cannot.
4. **`?overdue=false` is a silent no-op** — reads as "no filter" rather than "not overdue".
5. **A GET response cannot be PUT straight back** — `to_representation()` expands `customer` into
   an object; the writable field is a primary key.

Items 1 and 2 are money- and data-integrity issues and are Phase 3 work. Items 3-5 are contract
and usability issues, same phase, lower priority.

---

### 6. Environment strategy

| Environment | Purpose | Test types | Data | Deploy trigger |
|---|---|---|---|---|
| **Local** | Developer feedback | Unit, `check --deploy`, `tsc -b` | Dev PostgreSQL; `seed_test_users.py` for the three roles | On save |
| **CI** | Automated validation | Unit, Newman, static, migration drift | Ephemeral PostgreSQL 14 service container, seeded per run | Every push and PR |
| **Staging** | Pre-release validation | Manual E2E, the one real extraction test | Anonymised copy; a dedicated OpenAI key with its own spend cap | On merge to `master` |
| **Production** | Live | Smoke: login, dashboard loads, one invoice renders | Live | Manual |

**Test data.** The Newman suite is self-cleaning: `00 Setup` records baseline counts and
`99 Teardown` deletes everything created and asserts the baseline is restored, so two consecutive
runs are equally green. The three seeded role accounts persist by design. CI must use a
**throwaway database**, not a developer's — `on_delete=PROTECT` means an aborted run leaves
undeletable fixture rows behind.

**Secrets.** `SECRET_KEY` and `OPENAI_API_KEY` are both required with no default; the process
refuses to start without them. CI supplies both from repository secrets. **CI must never hold the
production OpenAI key** — folder `07 PDF extract` covers rejection paths only, all four of which
short-circuit before any model call, so CI needs a syntactically valid key that is never charged.

---

### 7. Tool selection

Weighted scoring, 1-5 per criterion. The decision under evaluation is the **unit-test runner**,
since every other layer is already chosen and working.

| Criteria (weight) | Django `TestCase` | pytest + pytest-django | unittest, hand-rolled |
|---|---|---|---|
| Fits tech stack (25%) | 5 | 5 | 3 |
| Team familiarity (20%) | 4 | 4 | 3 |
| Community and docs (15%) | 5 | 5 | 3 |
| CI integration (15%) | 5 | 5 | 4 |
| Maintenance cost (10%) | 5 | 4 | 2 |
| Speed of execution (10%) | 4 | 4 | 4 |
| **Dependency cost (5%)** | **5** (none) | **1** (new pip dep, needs approval) | 5 |
| **Weighted total** | **4.70** | **4.40** | **3.20** |

**Chosen: Django `TestCase`.** pytest scores close and is genuinely nicer to write, but the
tie-break is `conventions.md`'s dependency rule: `TestCase` needs no approval and the stub files
already import it. Revisit if the suite passes ~200 tests and fixture duplication starts to hurt.

**Already chosen, recorded for completeness:**

- **Postman + Newman** for the API layer. Run via `npx newman@6` — nothing enters
  `package.json`. 92 requests in about three seconds against a real database.
- **Playwright MCP** for E2E, driven by the repo's `ui-test` skill. Manual and agent-driven rather
  than scripted: eight journeys do not justify a scripted suite plus its selector maintenance,
  and the skill already encodes the server-startup preflight.

**Two dependencies requiring approval before adoption** (neither is assumed by this strategy):

| Dependency | Buys | Cost | Recommendation |
|---|---|---|---|
| `coverage` (pip) | Line and branch coverage percentages | One pip dependency; encourages chasing a number over naming cases | **Defer.** Track named-case coverage instead (section 10) — for a codebase this size, a checklist of behaviours that must have a test is more honest than a percentage. |
| `vitest` (npm) | Unit tests for `frontend/src/lib/money.ts` | One npm dependency plus config | **Recommend, pending approval.** `money.ts` is the only pure-logic frontend module, and it holds a real rounding defect. The defect is caught by a backend unit test plus a Newman assertion either way, so this is a convenience, not a necessity. |

---

### 8. Entry and exit criteria

**Unit.** *Entry:* the module has a documented contract, and `manage.py check` passes.
*Exit:* every branch of `scope_to_role` covered; the rounding cases from `docs/domain.md` covered
explicitly, including the three-lines-of-`0.25 x 0.50`-equals-`0.39` case; negative and zero
quantities covered; no skipped tests.

**API / integration.** *Entry:* unit tests pass; a PostgreSQL service is up; role accounts seeded.
*Exit:* 299/299 assertions pass; `99 Teardown` restores the baseline counts; the collection-level
`no server error (5xx)` assertion passes on all 92 requests.

**E2E.** *Entry:* API tests pass; both servers running; the three role accounts exist.
*Exit:* all eight journeys pass; no P0 or P1 defects open; every screen touched has had the
`design-tokens.md` grep audit re-run.

**Release.** *Entry:* all levels pass; `check --deploy` returns 0 issues; `DEBUG` is `False`;
`SECRET_KEY` is not the `django-insecure-` default; no CRIT-band risk unmitigated.
*Exit:* production smoke passes (login, dashboard, one invoice renders); no 5xx in logs for a
**30-minute bake window**; rollback verified as the previous commit plus `migrate` reversibility
confirmed on staging first.

---

### 9. Quality gates

Every threshold below is machine-checkable. A gate that can be clicked past is documentation.

**PR gate** — every pull request, blocking:

| Check | Threshold |
|---|---|
| `python manage.py check --deploy` | **0 issues** |
| `python manage.py makemigrations --check --dry-run` | no changes detected |
| `python manage.py test` | 100% pass, 0 skipped |
| `npx newman run ... --working-dir fixtures` | **299/299 assertions**, 0 failed |
| `npm run build` (`tsc -b && vite build`) | exit 0 |
| `npx oxlint` | 0 errors |
| Pipeline wall clock | **under 5 minutes** |

**Merge gate** — merging to `master`: all PR-gate checks green on a branch up to date with
`master`; if any file under `frontend/src` changed, the three `design-tokens.md` grep audits
return their expected counts (0 / exactly 1 / 0).

**Deploy gate** — before production: all eight E2E journeys passed on staging within the last 24
hours; `DEBUG=False` and a strong `SECRET_KEY` confirmed in the target environment; login
throttling verified returning 429; a migration rollback rehearsed on staging.

**Nightly gate** — scheduled: full Newman run against staging; `pip list --outdated` and
`npm outdated` reviewed; PostgreSQL version re-checked against the Django 5.2 pin
(`conventions.md` — raising the pin requires upgrading PostgreSQL first); OpenAI spend for the
previous day reviewed against its cap.

---

### 10. Metrics and KPIs

| Metric | Definition | Target | Cadence |
|---|---|---|---|
| **Deploy check warnings** | `manage.py check --deploy` issue count | **0** (today: 6) | Every push |
| **API assertion pass rate** | Newman assertions passed / total | **299/299**, 0 failed | Every push |
| **Named-case coverage** | Behaviours on the section 8 checklist that have a test | **100%** of listed cases | Monthly |
| **Unit test count** | `manage.py test` collected tests | **70** by week 10 (today: 0) | Monthly |
| **Test pyramid ratio** | Unit : API : E2E | **41 : 54 : 5** (+/- 10%) | Monthly |
| **Known gap count** | Green `KNOWN GAP:` Postman requests | **0** by week 14 (today: 5) | Per release |
| **Flakiness rate** | Runs failing non-deterministically | **under 1%** | Weekly |
| **CI pipeline duration** | Push to green/red signal | **under 5 min** | Weekly |
| **Defect escape rate** | Defects found post-release / total found | **under 10%** | Per release |
| **MTTR** | Detection to fix deployed | **under 24h P0, under 1 week P1** | Per incident |
| **Doc-code drift** | Claims in `docs/` contradicted by behaviour | **0** (today: 1 — the `money.ts` rounding claim) | Quarterly |
| **OpenAI spend** | Daily extraction cost against cap | **within cap**, no cap breach | Daily |

Two notes on reading these. **Named-case coverage replaces a line-coverage percentage** on
purpose — see section 7; it needs no new dependency and it forces naming the behaviour rather than
chasing a number. **Doc-code drift is tracked as a first-class metric** because this repo's
documentation is unusually load-bearing: `AGENTS.md`, `domain.md` and `conventions.md` are the
onboarding path, and a false claim in them costs more here than a stale comment would elsewhere.
It is at 1, not 0, today.

Track trends, not absolutes. Never use these to assign blame.

---

### 11. Timeline and milestones

Calibrated to **one contributor**. Phases are sequential; each exit criterion is a command.

**Phase 1 — Make it safe to ship (weeks 1-4).** Close all six `check --deploy` warnings. Add DRF
throttling to `/api/auth/login/` and assert the 429 in Newman. Write the OpenAI data-flow note:
what leaves the server, to whom, under what agreement, with what retention. Stand up GitHub
Actions with a PostgreSQL 14 service container running the full PR gate.
*Exit: CI green on every push; `check --deploy` returns 0 issues.*

**Phase 2 — Base the pyramid (weeks 5-10).** Roughly 70 Django `TestCase` tests over
`Transaction.line_total`, `Invoice.total`, the dashboard's Round-inside-Sum aggregate, and
`scope_to_role()` — whose own docstring calls it *"the single most drift-prone line in the
project."* Amend decision log #2 to record the reversal.
*Exit: reverting the `quantize()` call in `line_total`, or the STAFF branch in `scope_to_role`,
each makes a named test fail.*

**Phase 3 — Close the known gaps (weeks 11-14).** Validate `quantity` and `unit_price`; reconcile
`money.ts` with `ROUND_HALF_UP`; add `InvoiceSerializer.validate()` for the date ordering; fix
`?overdue=false`; resolve the invoice-number search — implement it in the filter layer by parsing
digits back to a primary key, or remove the placeholder that promises it.
*Exit: 5 known gaps to 0; `docs/domain.md`'s claim about `money.ts` becomes true; doc-code drift
metric reaches 0.*

**Phase 4 — Gates and review (weeks 15-20).** Enforce all four gates. Add the nightly schedule.
Publish revision 1.1 of this document.
*Exit: all four gates active; first quarterly revision recorded in section 13.*

**Ongoing:** quarterly review of this document; monthly metrics review; the `design-tokens.md`
grep audit after every UI change.

---

### 12. Risks to the strategy itself

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Single contributor.** One person is author, implementer and reviewer. No second pair of eyes, and a bus factor of one. | High | CI gates are the substitute reviewer: they cannot be talked out of a failure. Every gate is machine-checked precisely because there is no human reviewer to catch what it misses. |
| **Phase 1 hardening never finishes** because the app "works fine locally". | High | It is Phase 1 for exactly this reason. `check --deploy` is one command; there is no research needed, only the doing. |
| **Newman drifts from the API** as endpoints change, and nobody notices because it is not in CI. | High until Phase 1 | Fixed by Phase 1 — once it runs on every push, drift surfaces the same day. |
| **`KNOWN GAP` tests calcify** into "that is just how it works" instead of being closed. | Medium | The known-gap count is a tracked KPI with a target of 0 and a date (week 14). |
| **PostgreSQL 14 blocks a needed Django upgrade.** The pin is a ceiling; that server hosts other databases. | Medium | Nightly gate re-checks the PG version. A security release requiring Django 6.x makes this urgent overnight; treat the upgrade path as a known, unscheduled dependency. |
| **OpenAI changes model behaviour or pricing** under the extraction feature. | Medium | Rejection paths are asserted and cost nothing. The happy path is reviewed by a human by design, so a quality regression degrades rather than corrupts. Spend is a daily metric. |
| **This document goes stale** and becomes the false confidence it was written to remove. | Medium | Quarterly review; a named owner; the revision history below. Re-evaluation triggers: a new product area, a defect escaping to production, any change to the money rule or the role matrix. |

---

### 13. Revision history

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-08-25 | Darshil Babel | Initial strategy. Baseline measured: 0 unit tests, 92 Newman requests / 299 assertions, no CI, 6 `check --deploy` warnings, 5 documented known gaps. Proposes a scoped reversal of `architecture.md` decision log #2 covering money arithmetic and role scoping only, at zero new-dependency cost. |

**Next review due:** 2026-11-25 (quarterly), or immediately on any of the re-evaluation triggers in
section 12.
