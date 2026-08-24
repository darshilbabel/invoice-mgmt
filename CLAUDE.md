# CLAUDE.md

Router file. Claude Code loads this automatically; everything substantive lives in the files it
points to below, so this stays short and doesn't drift out of sync with them.

@AGENTS.md

## Architecture, in five lines

Django + DRF API (`backend/`) and a React + TypeScript SPA (`frontend/`) talk over HTTP.
`accounts` owns the user model, `billing` owns `Customer` / `Invoice` / `Transaction`. Invoice
totals are always computed from transactions, never stored. Permissions are role-based
(`ADMIN` / `STAFF` / `VIEWER`) and enforced by one scoping function reused everywhere it applies.
The frontend is built on the SkilloVilla design system — don't hand-tune its tokens.

Full detail: @docs/architecture.md @docs/domain.md @docs/conventions.md @docs/design-tokens.md

## Working inside `backend/` or `frontend/`

Each has its own `CLAUDE.md` with stack-specific patterns — Claude Code loads it automatically
when you're working in that directory. Don't duplicate their content here.

## Do not

- Hand-edit a file under `migrations/`.
- Add a pip or npm dependency without asking first (`docs/conventions.md` has the approved list).
- Build anything beyond what the active ticket in `docs/specs/` asks for.
- Skip stating a verification step for a plan item — there is no test suite to catch you if it's
  wrong (see `docs/architecture.md`'s decision log for why).
