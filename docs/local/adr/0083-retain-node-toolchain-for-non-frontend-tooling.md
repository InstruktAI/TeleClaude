---
visibility: internal
number: 0083
date: 2026-09-08
description: bin/install.sh keeps requiring and provisioning Node/corepack after the frontend removal, because non-frontend tooling still depends on it.
---

# Retain Node Toolchain For Non-Frontend Tooling — ADR

## Context

ADR-0082 deleted `frontend/` and stated, in its Consequences, that "nothing
left in the repository needs a Node toolchain to install or lint." That claim
was checked against the repository's own root-level Node workspace
(`package.json`, `pnpm-lock.yaml`, `pnpm-workspace.yaml`), whose only
dependencies (`jsdom`, `tsx`, `dompurify`) turned out to serve the frontend
alone — its tests, its custom dev server, and one of its components — and were
removed alongside it. But `bin/install.sh`'s `check_node()`/`setup_corepack()`
were left untouched during that same pass, and a review of the removal
correctly asked whether that left the ADR's claim and the repository's actual
behavior in conflict: a fresh install still hard-requires Node.

The two candidates for closing that gap are genuinely different: strip Node
provisioning from `install.sh` to make the claim true, or keep it because Node
serves purposes ADR-0082 never considered.

## Decision

Keep `bin/install.sh`'s Node/corepack provisioning. It is not frontend-specific
and was never made so by ADR-0082: `tools/quality.sh`'s guardrails lane runs
prettier/eslint/tsc/jscpd via `pnpm exec`/`npx`, needed for this repository's
own markdown/YAML formatting and duplication detection independent of any
frontend; and `teleclaude/core/next_machine/worktrees.py` runs `pnpm
install`/`npm install` when provisioning a worktree for any TypeScript-based
project TeleClaude manages, not only this one. Removing Node here would break
both.

## Consequences

- ADR-0082's Consequences claim ("nothing left needs a Node toolchain") is
  narrower than stated: install still requires Node, but for reasons that were
  never about the frontend. ADR-0082's `## Status` points here rather than
  restating the correction in its own immutable body.
- `bin/install.sh` is unchanged by the frontend removal; only the root-level
  Node workspace files that existed solely for the frontend are gone.
- A future removal of the guardrails lane's Node dependency, or of
  cross-project TypeScript worktree support, would be its own decision — this
  ADR does not anticipate or authorize either.

## Alternatives Considered

- **Strip `check_node()`/`setup_corepack()` from `install.sh` to match the
  original claim literally.** Rejected: this would break `telec code lint`'s
  guardrails lane and cross-project worktree setup, which have nothing to do
  with the frontend that was actually removed. Making a claim true by breaking
  unrelated functionality is the wrong fix for an overclaim.
