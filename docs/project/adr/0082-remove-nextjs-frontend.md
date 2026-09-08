---
visibility: internal
number: 0082
date: 2026-09-08
description: The Next.js browser frontend is removed from the repository rather than fixed or maintained.
---

# Remove Next.js Frontend — ADR

## Context

`frontend/` held a Next.js web application — a browser UI proxying to the TeleClaude
daemon, independent of the Python TUI, with its own context root, dependency
toolchain, dev server, and E2E/visual-regression harness. Work against it kept
surfacing friction: a fresh worktree needed several undocumented manual steps
before its own verification procedure could even run, and its E2E suite carried
an unusable default test identity. The application itself saw no real usage — the
TUI remained the actual operating surface — while its toolchain and checkpoint
overlay continued to cost maintenance attention.

## Decision

Delete `frontend/` in its entirety. The Next.js web application is not repaired,
migrated, or replaced — it is removed. TeleClaude's browser-facing surface reverts
to none; the Python TUI remains the sole first-party UI.

## Consequences

- The frontend's dependency toolchain (pnpm, Next.js, Playwright), its dedicated
  context-root checkpoint overlay, and its E2E/visual-regression harness are gone.
  Nothing left in the repository needs a Node toolchain to install or lint.
- The architecture and verification docs that existed only to describe this
  application (`project/design/architecture/frontend`, `project/design/architecture/web-api-facade`,
  `project/design/architecture/web-interface`, `project/procedure/frontend-verification`)
  are removed rather than kept as stubs — there is no contract left for them to
  describe.
- `docs/project/policy/test-moratorium.md`'s frontend-specific clauses (the
  mandatory frontend-verification procedure, the required two-theme
  screenshot-regression harness) no longer apply and are removed from that policy;
  its Python-verification rules are unaffected.
- `bin/install.sh`'s frontend setup functions and the Makefile's `generate-types`
  target (which wrote into `frontend/lib/...`) become dead code and are removed
  alongside.
- A browser-facing UI, if wanted again, starts from a fresh decision and a fresh
  build — none of the removed application, its route map, or its verification
  harness is salvaged as a starting point.
- TeleClaude loses any browser-reachable surface. Anything that depended on the
  web API facade (`/api/*` proxy routes) or the browser chat/session UI has no
  replacement.

## Alternatives Considered

- **Fix and keep it.** Rejected: the friction was not one bug but a pattern of
  first-run and identity gaps discovered every time it was touched, against an
  application with no established real usage to justify the ongoing cost.
- **Archive instead of delete.** Rejected: an unmaintained frontend left in the
  tree invites the same drift that produced the friction in the first place, and
  git history already preserves the code if it is ever wanted back.
