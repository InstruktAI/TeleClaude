---
description: "Wire the visual snapshot and smoke suites into a frontend repo: sitemap-walking spec, determinism knobs, buttons, CI hookup, baselines, and the approval-loop stanza for the repo's AGENTS.md."
---

# Setup Visual Regression — Procedure

## Goal

Give a frontend repo its two guard rails: a sitemap-driven visual snapshot
suite (local instrument) and a smoke suite (CI gate), wired to the standard
buttons so agents and CI push them blindly.

## Preconditions

- The repo builds a sitemap (frontend production baseline requirement).
- Reached through the greenfield intake's gate-wiring step, or through a
  reviewer finding that flags the suites as missing (retrofit).

## Steps

1. Pin the test runner (`@playwright/test`) as a devDependency. Locally the
   suites run on the installed system browser (`channel: 'chrome'`); CI
   installs its own browser behind an environment flag. Never download
   browsers into a dev machine.
2. Serve the production build on a dedicated port for tests; the test scripts
   run the build first so specs can read `dist/` at load time.
3. Visual spec: parse the built sitemap for the URL set, multiply by themes,
   snapshot each page full-page against committed baselines
   (platform-keyed paths). Tolerate antialiasing drift only.
4. Smoke spec: every sitemap URL returns 200, applies the stylesheet, and
   logs zero console/page errors.
5. Determinism knobs in both specs: abort requests to external hosts (live
   data must render its deterministic fallback state), disable animations,
   fix viewport and device scale.
6. Wire the buttons: `test:visual`, `test:visual:update`, `test:smoke`
   scripts; the Makefile maps `e2e` to the smoke suite (the CI-portable
   lane). Hook CI through the shared reusable workflow.
7. Generate the first baselines, eyeball a sample, and commit them with the
   wiring.
8. Seed the repo's AGENTS.md with the approval loop: run the visual suite
   after any change that could touch rendering; review failing diffs; only
   when they match approved intent, re-baseline — the new baselines commit
   together with the change.

## Outputs

- Passing visual and smoke suites, committed baselines, buttons and CI gate
  wired, AGENTS.md carrying the approval loop.

## Recovery

- Baselines diverging on another machine are expected (platform-keyed);
  regenerate locally rather than committing cross-platform diffs.
- Flaky snapshots trace to a determinism knob left open (an unblocked host,
  a running animation) — close the knob, never widen the diff tolerance.

## See Also

- ~/.teleclaude/docs/software-development/policy/frontend-production-baseline.md
- ~/.teleclaude/docs/software-development/policy/ci-pipeline-conventions.md
