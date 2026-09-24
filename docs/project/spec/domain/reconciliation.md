---
visibility: internal
description: Frozen v1 ownership anchor for installation and fleet convergence behavior.
---

# Reconciliation Domain Spec — Spec

## What it is

The v1 reconciliation area compares declared installation capabilities with
observed machine state and drives the supported convergence paths. It is a
maintenance-only appliance surface, not the replacement reconciliation design.

## Canonical fields

- **Current behavior:** reconciliation feature specs and operational contracts
  that require this anchor.
- **Implementation roots:** `teleclaude/core/reconciliation/` and sanctioned
  installation/service-control surfaces.
- **Maintenance stance:** see `project/spec/domain/glossary`. Replacement fleet design belongs to
  TeleClaudeNext.

### Ownership boundary

- **Owns:** comparison of declared installation capabilities with observed
  machine state and selection of sanctioned convergence actions, including the
  rule deciding which material the home's history retains.
- **Does not own:** service lifecycle mechanics, configuration schema, the
  application behavior of the capabilities it reconciles, or what a commit
  boundary does with a membership answer it is given.
- **Published contracts:** reconciliation observations, plans, and outcomes
  consumed by sanctioned installation and service-control surfaces; and a
  membership predicate returning, for any path, exactly one of `retained`,
  `not-retained`, or `outside` — the last where the path resolves beyond the home
  root. The predicate reports membership only; the consumer's response to a
  result is that consumer's own contract.
- **Also published:** fleet discovery facts for this installation — which node
  is the mesh master, and which capabilities this node advertises — carried on
  the heartbeat as additive fields and readable by every peer. The context owns
  the declaration and its advertisement only; which capability a consumer
  requires before coordinating, and what it does when a peer lacks it, is that
  consumer's own contract.

#### Use cases (index of feature specs)

- **project-plumbing-convergence** — `docs/project/spec/feature/reconciliation/project-plumbing-convergence.md` — converging a project's installed git hooks and docs filter driver to its declared capabilities
<!-- planned:home-tier-commit-maintenance -->
- **home-template-materialization** — `docs/project/spec/feature/reconciliation/home-template-materialization.md` — materializing repository-owned regular-file templates into the TeleClaude home before activation
<!-- /planned:home-tier-commit-maintenance -->
<!-- planned:installable-template-trees -->
- **template-installation** — `docs/project/spec/feature/reconciliation/template-installation.md` — rendering and naming every repository-owned template TeleClaude installs onto a machine or into a project
<!-- /planned:installable-template-trees -->


## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
