---
description: 'TeleClaude keeps its installer in bash and collapses to one context-aware `make install`; the Makefile becomes a thin delegation surface. No Python rewrite.'
date: 2026-06-13
number: 48
---

# make install: single bash entry, context-aware mode — ADR

## Context

TeleClaude's root `Makefile` carried two divergent realities. Quality recipes
(`lint`/`format`/`test`) embedded multi-step bash orchestration inline. The
install surface diverged into three entry points: `make install` (a ~30-line
inline deps block — uv, frontend, telec-daemon build, git hook), and the full
machine-global setup hidden behind the deprecated `make bootstrap` /
`make bootstrap-ci` (both wrapping `bin/install.sh`). The telec→Makefile
deferral paradigm and the single-`make install`-setup-surface contract were
already delivered; the Makefile and installer had not been brought to match.

An earlier roadmap proposed inverting the whole toolchain into Python — a
testable Python installer and `tools/quality.py`. That direction was abandoned:
`bin/install.sh` is ~90% idempotent shell-out (detect, brew/apt/`curl|sh`, copy,
symlink, PATH), where a Python rewrite would buy only a mock-echo test surface
asserting "I called brew" — the fake-test anti-pattern the platform forbids. The
genuinely logic-y config already lives in Python helpers
(`bin/init/configure_agent_cli.py`, inline `_yaml_python`). The remaining problem
was never the language; it was the inline-logic and the multi-entry divergence.

## Decision

The installer stays bash and is cleaned up, not rewritten. The win is
consolidation, not a language change.

- `make install` is the single install entry. Its recipe is a one-line
  delegation to `bin/install.sh`; `make bootstrap` and `make bootstrap-ci` are
  removed and their call sites migrate to `make install`.
- `bin/install.sh` selects its mode from execution context: running inside a
  linked git worktree → deps-only (replacing the prior refuse-from-worktree
  hard-exit); the `CI` environment variable set → CI mode; otherwise → full
  machine-global (interactive only when a TTY is present). Explicit flags
  override auto-detection. This keeps every existing bare `make install` caller —
  the worktree-prep fallback and the CI workflows — working unchanged.
- Quality recipes relocate their inline orchestration into a shellcheck-clean
  bash `tools/quality.sh`; recipes become one-line delegations. Together with the
  install change the Makefile becomes a fully thin convention surface, per the
  Makefile-no-inline-logic policy.
- The toolchain-inversion _design_ is unchanged: make owns the native toolchain
  and stays a thin convention surface, and adopting projects stay standalone.
  Only the implementation language decision is settled here.

## Consequences

- One install path removes the `make install` vs `make bootstrap` divergence that
  was a recurring source of confusion. The `make install` target name — a
  referenced contract in checkpoint evidence, README, and error feedback —
  persists.
- A worktree `make install` now runs deps-only instead of being refused, so the
  generic worktree-prep fallback is safe and lean without per-worktree launchd or
  service installs.
- The installer remains shell — readable, honest about being shell-out, and not
  carrying a hollow test surface. Future install logic that genuinely earns a
  test moves into the existing Python helpers, not into a wholesale rewrite.
- Mode auto-selection is now load-bearing: a wrong context detection would run
  the wrong install mode. The detection is small and explicit, and explicit flags
  override it; if any site proves unsound under auto-detection, that site uses an
  explicit selector instead.

## Alternatives Considered

- **Rewrite the installer in Python** (the abandoned `python-installer-rewrite` /
  `consolidate-make-install` slices). Rejected: idempotent shell-out is not logic
  a Python port makes safer; it would produce a mock-echo test surface, the
  anti-pattern the platform forbids.
- **Keep `make install` lean (deps-only) and leave full setup behind a separate
  entry.** Rejected: it fights the delivered single-setup-surface contract, where
  `make install` _is_ the machine setup surface, and preserves the very
  divergence this decision removes.
