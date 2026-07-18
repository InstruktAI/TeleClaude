---
description: 'The two-tier Makefile button contract (fast agent loop vs heavy e2e lane) and the reusable GitHub workflow catalog: what CI pushes, where shared pipelines live, and the itsUP exception.'
---

# CI Pipeline Conventions — Policy

## Rules

### The two-tier button contract

- Every repo's Makefile exposes the **agent loop**: `lint`, `format`, `test`,
  `install` — fast by design, safe to run on every change. `telec code`
  drives these.
- Every repo with heavy verification adds the mandatory **delivery lane**:
  `make e2e` — the suites too slow for the agent loop (browser/visual suites
  for sites, integration harnesses for services, release-grade test runs).
  CI is its only routine caller.
- CI composition is therefore universal and repo-blind: fast job runs
  `make lint test`, gate job runs `make e2e`, deploy runs after both.
- Frontend repos implement the Makefile as a thin shim delegating to their
  `package.json` scripts (see the frontend production baseline's button set);
  the Makefile stays the single cross-language interface.

### Reusable workflows

- Generic pipelines live as `workflow_call` workflows in the dedicated
  **`InstruktAI/workflows`** repo, consumed by version tag:
  `uses: InstruktAI/workflows/.github/workflows/<name>.yml@v1`.
- The catalog stays thin precisely because of the button contract: each
  workflow is checkout → toolchain setup → `make` buttons → deploy step.
  Starting set: `ci-node`, `ci-python`, `ci-rust`, `deploy-cloudflare`.
- **Target-owned deploy workflows stay with their target.** itsUP's
  `reconcile.yml` lives in `Morriz/itsUP` because itsUP _is_ the deployment
  target; app repos call it directly with `secrets: inherit`. Do not mirror or
  wrap it in the workflows repo.
- Private-repo reuse requires the workflows repo's access setting
  "accessible from repositories in the organization" — set once.

## Rationale

`make test` must stay fast or agents stop running it; heavy suites must gate
releases or regressions ship. Two named tiers keep both true and give CI one
standardized entry across every language and flavor. Centralizing the generic
pipelines removes per-repo YAML drift, while the itsUP exception keeps
domain-owned plumbing (VPN, SSH, reconcile semantics) in the repo that owns
the domain.

## Scope

All repos with CI, all flavors. The `e2e` target is mandatory wherever a
delivery gate exists (every deployed site and service); pure libraries and
scripts may omit it.

## Enforcement

- A deployed repo whose CI does not run `make e2e` (or whose Makefile lacks
  the target) fails review.
- New per-repo workflow YAML that duplicates a catalog pipeline is a defect —
  consume the reusable workflow instead.

## Exceptions

- Repos with genuinely bespoke pipelines (the workflows repo itself, itsUP)
  own their YAML outright.

## See Also

- ~/.teleclaude/docs/software-development/design/project-toolchain.md — the Makefile contract this extends.
- ~/.teleclaude/docs/software-development/policy/frontend-production-baseline.md — the frontend script buttons behind the shim.
