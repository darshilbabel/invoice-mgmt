# Design tokens

The UI is built on the **SkilloVilla design system**, imported from the Claude Design project
`Invoice management system design` (`74a9a9d6-c711-4001-a15a-677b568dd223`). Tokens are ported
verbatim into `frontend/src/styles/tokens.css` — change the design system and re-port rather than
hand-tuning values there. See `frontend/CLAUDE.md` for how components consume them.

## Hard rules

From the system's own readme. Do not relax these:

- **Figtree only**, self-hosted at `frontend/public/fonts/`. It is a *variable* font — one file
  covers weights 300–900, declared with a weight range. Do not add one `@font-face` per weight;
  that was tried once and produced five byte-identical downloads.
- **The violet→amber gradient is only ever a 4px rule.** Never a background, never a button fill,
  never behind text. In this app it appears in exactly one place: `.topbar-rule`.
- **Amber is accent only, and in this app it means exactly one thing:** a field the PDF extractor
  read with low confidence, on `/invoices/upload/review` and nowhere else. Fill `--warning-tint`,
  1.5px field border `--warning`, text `--amber-800` (`--amber-500` on white fails contrast; the
  system's own rule is amber-700+ when text is unavoidable). **Overdue is not amber** — it is a
  danger state and takes `--danger` red, on every screen including that one. If you find yourself
  reaching for amber on any other screen, the answer is no.

  *Until the extraction review screen arrived this app used no amber at all. "Low confidence, look
  here" is the one signal in the product that is genuinely neither neutral nor an error, which is
  what the accent is for.*
- **Buttons are always pill** (`--radius-pill`). Cards 12px, inputs 8px, dialogs 16px.
- **Focus is a 3px `--focus-ring`**, never removed.
- **Sentence case everywhere**; the 11px eyebrow label is the only uppercase text. **No emoji,
  anywhere.**
- Ink is plum-tinted `#2b2531`, never pure black. Backgrounds are flat; there is no imagery,
  because none was ever supplied to the design system.

## Palette

| token | value | use |
|---|---|---|
| `--brand` / `--violet-500` | `#9431fe` | primary buttons, links, active states |
| `--brand-deep` / `--violet-900` | `#340a62` | the login split-panel only |
| `--text-strong` / `--ink-900` | `#2b2531` | headings |
| `--text-body` / `--ink-800` | | body text |
| `--danger` / `--red-500` | `#e5484d` | overdue badges, delete confirmation |
| `--warning` / `--amber-500` | `#ffa800` | low-confidence field border, review screen only |
| `--amber-800` | `#7a4a00` | the only amber that may carry text |
| `--gradient-brand` | violet → amber, 90° | the 4px rule, nowhere else |

Full ramps (violet/amber/ink 50–950, semantic green/red/blue) are in `tokens.css`.

## Type

Role aliases — `--type-h1` through `--type-eyebrow` — combine weight, size and line-height in one
declaration. Prefer `font: var(--type-body-sm)` etc. over composing the pieces by hand.

## Wireframe provenance

The design canvas offered ten competing options across five screens; the ones built are recorded
in `architecture.md`'s routes table. `/customers` is the one screen with **no wireframe** — it
was built to match 1c's table rhythm so it reads as part of the set.

A later turn on the same canvas added `3a`–`3d`, the PDF upload flow. Three deviations from what
it drew, all deliberate:

- **No gradient rule under the review screen's page head.** The canvas drew a second one; it was
  cut so the signature gradient stays unique to `.topbar-rule`.
- **No `✓` or `!` glyphs** in the step list and the notices. The system permits only `×` and the
  `Select` chevron as unicode standing in for an icon, so state is carried by colour and shape.
- **No percentage or time remaining** on the progress bar. Reporting either needs a polled job;
  the endpoint is a single blocking call, so the bar is indeterminate.

## Audit

Re-run after any UI change:

Quote the `--include` patterns — zsh expands them itself otherwise and the grep finds nothing,
which reads exactly like a pass.

```bash
cd frontend
# expect zero matches — every colour must come from a token
grep -rn '#[0-9a-fA-F]\{3,8\}' src '--include=*.css' '--include=*.tsx' | grep -v tokens.css

# expect exactly one match — .topbar-rule. (tokens.css is excluded because the
# line that DEFINES the gradient lives there and always matches.)
grep -rn 'gradient-brand' src | grep -v tokens.css

# expect zero — no unicode glyph may stand in for an icon, and no emoji anywhere
grep -rn '[✓✗✕→←▾•★]' src '--include=*.tsx' '--include=*.css'
```

Contrast is not part of this audit — no grep catches it. The two pairings that were flagged as
failing WCAG AA (`--text-subtle` in table headers at 3.46:1, and on `.hint`/`.subtle` at 3.61:1,
against 4.5:1 for text that size) are **fixed**: all three now take `--text-muted`.

`--text-subtle` is still in the token set and still used elsewhere — `.crumb`, `.tile-label`,
`.cell-sub`, `.eyebrow`, input placeholders. Those were not part of the flagged finding and have
not been measured. Treat `--text-subtle` as suspect for anything that has to be *read* rather than
scanned.
