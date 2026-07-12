---
visibility: internal
description: Frozen v1 ownership anchor for external-provider and process-boundary integration behavior.
---

# Integration Domain Spec — Spec

## What it is

The v1 integration area inventories behavior crossing provider, process, and
delivery boundaries, including inbound adapters, outbound notifications, agent
hook reception, and code-integration workflow surfaces. Its feature specs and
implementation remain the current appliance contract.

## Canonical fields

- **Current behavior:** `docs/project/spec/feature/integration/`.
- **Implementation roots:** `teleclaude/adapters/`,
  `teleclaude/core/integration/`, `teleclaude/core/inbound/`, and
  `teleclaude/events/delivery/`.
- **Maintenance boundary:** only approved v1 P0 fixes may alter this area; no
  replacement transport design is authored here.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
