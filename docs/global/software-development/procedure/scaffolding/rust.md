---
description: 'Rust scaffolding guidance: the systems flavor for long-running, unattended, non-public-facing infrastructure.'
visibility: 'public'
---

# Rust Scaffolding — Procedure

## Goal

Scaffold the systems flavor: daemons, watchers, and performance-sensitive
tools that run for months without a human, where reliability and footprint
dominate iteration speed.

## Preconditions

- Portfolio classification: systems/daemon. The boundary is sharp — Rust
  never creeps into websites (TypeScript owns the web) or one-off automation
  (Python owns glue).
- `rust` declared in `teleclaude.yml` so `telec code` drives Cargo natively.

## Steps

1. Scaffold with `cargo new` (binary) or `cargo new --lib`; single Cargo
   workspace at the repo root.
2. Apply the platform's Rust policies (`software-development/policy/rust/core`
   and `rust/testing`) — they own idiom, DI, and test shape.
3. Clippy + rustfmt are the lint/format lane; the compiler is the built-in
   reviewer — treat warnings as errors in CI.
4. Single-binary delivery, self-hosted (itsUP or native service); no runtime
   dependencies.
5. Wire the Makefile buttons (`lint`/`format`/`test` via Cargo, `e2e` for
   release-grade/integration runs) and the `ci-rust` reusable workflow.

## Outputs

- A Cargo workspace with buttons, CI, and delivery wired.

## Recovery

- If iteration speed starts dominating (product experiments, UI work), the
  workload was misclassified — move it to the appropriate flavor.

## See Also

- ~/.teleclaude/docs/software-development/concept/delivery-portfolio.md
- ~/.teleclaude/docs/software-development/policy/ci-pipeline-conventions.md
