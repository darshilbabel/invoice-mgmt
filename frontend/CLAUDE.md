# frontend/CLAUDE.md

React + TypeScript specifics. Repo-wide rules are in the root `CLAUDE.md` / `AGENTS.md`; the
design system's hard rules are in `../docs/design-tokens.md`; the API contract this app talks to
is in `../docs/architecture.md`.

## Structure

```
src/
├─ api/          client.ts (the only place fetch happens), customers.ts (pagination walk)
├─ auth/         AuthContext.tsx
├─ components/   AppShell.tsx, ProtectedRoute.tsx
├─ lib/          money.ts
├─ pages/        one file per route
├─ styles/       tokens.css — do not edit, see design-tokens.md
└─ types.ts
```

## `types.ts` has no independent source of truth

It's a hand-maintained mirror of the DRF serializers. When a backend serializer field changes,
`types.ts` changes in the same commit — there is no codegen step to catch drift, so a mismatch
here is a silent runtime bug, not a compile error, until something touches the mismatched field.

## `api/client.ts`

- Every request goes through `api.get/post/put/patch/delete` — never call `fetch` directly from
  a page or component.
- A 401 clears the token and redirects to `/login` **only if a token was actually presented and
  the request wasn't itself a login attempt**. Treating a wrong-password 401 from `/auth/login/`
  as "session expired" would sign a user out of a session they don't have yet, and bounce them
  off the very page they're on. If you touch the 401 branch, keep that distinction.
- Errors are `ApiError` with a `.message` that already flattens DRF's two error shapes
  (`{detail}` vs `{field: [...]}`) into something showable. Render `.message` directly; don't
  re-derive it from `.body`.

## `api/extraction.ts`

Wraps `POST /api/invoices/extract/`, which reads an uploaded PDF with OpenAI. Two things about it
shape the UI around it:

- **It is slow and it blocks.** There is no job queue behind it, so the request is open for the
  whole model call — up to `OPENAI_TIMEOUT_SECONDS` (90). That is why `InvoiceUpload` has a real
  waiting state with an indeterminate bar, and why `api.upload` takes an `AbortSignal`.
- **It creates a `Customer` when the supplier matches nothing.** The response carries
  `customer_created`, and the review screen has to say so — a row appears whether or not the user
  goes on to save. Do not quietly drop that badge.

Its `validateFile` check is a courtesy that avoids uploading 10 MB to be told no. The server
enforces the real limit and checks the PDF magic bytes; never treat the client check as the control.

`api.upload` in `client.ts` sets no `Content-Type` on purpose — the browser must write it so the
multipart boundary matches the body. Setting it by hand produces a request the server cannot parse
and no useful error.

## Money

Never parse an API money value into a `number` except for transient display math (`lib/money.ts`).
Never send a `number` back to the API for a money field — always the string the form built.
`lib/money.ts::lineTotal` mirrors the server's per-line-then-sum rounding rule; if the server rule
in `../docs/domain.md` changes, this must change with it or the two totals will visibly disagree.

## Design tokens

Read `../docs/design-tokens.md` before touching any CSS. The short version: everything comes from
`styles/tokens.css`; the gradient is a 4px rule and nowhere else; amber means "low confidence" on
`/invoices/upload/review` and is used on no other screen; buttons are pill. Run the audit commands
in that doc after any styling change — three greps, and they catch the mistakes that are easy to
make by accident. Quote the `--include` patterns or zsh eats them and every grep looks clean.

## Known gap

The flagged contrast failure is fixed: `thead th`, `.hint` and `.subtle` moved from
`--text-subtle` to `--text-muted`. `--text-subtle` survives on `.crumb`, `.tile-label`,
`.cell-sub`, `.eyebrow` and input placeholders — unmeasured, so treat it as suspect for anything
meant to be read rather than scanned. See `../docs/design-tokens.md`.

## Verification

No test suite. `npx tsc --noEmit` is fast but weaker than the real gate:

```bash
npm run build     # tsc -b && vite build — this is what actually catches type errors in this template
```

Then a browser pass against a running `manage.py runserver` — there is no way to verify a UI
change without one.
