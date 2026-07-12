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
- **Maintenance boundary:** only approved v1 P0 fixes may alter convergence
  behavior. Replacement fleet design belongs to TeleClaudeNext.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
