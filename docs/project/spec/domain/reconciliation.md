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

<!-- planned-change:person-home-repository -->
- **Owns:** comparison of declared installation capabilities with observed
  machine state and selection of sanctioned convergence actions.
- **Does not own:** service lifecycle mechanics, configuration schema, or
  application behavior of the capabilities it reconciles.
- **Published contracts:** reconciliation observations, plans, and outcomes
  consumed by sanctioned installation and service-control surfaces.
<!-- change:person-home-repository -->
- **Owns:** comparison of declared installation capabilities with observed
  machine state and selection of sanctioned convergence actions, including the
  rule deciding which material the home's history retains.
- **Does not own:** service lifecycle mechanics, configuration schema, the
  application behavior of the capabilities it reconciles, or what a commit
  boundary does with a membership answer it is given.
- **Published contracts:** reconciliation observations, plans, and outcomes
  consumed by sanctioned installation and service-control surfaces; and a
  membership predicate answering, for any absolute path, whether it belongs to
  the home's retained set.
<!-- /planned-change:person-home-repository -->

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
