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
- **Implementation roots:** `teleclaude/adapters/`, `teleclaude/core/inbound/`,
  `teleclaude/core/delivery/`, `teleclaude/transport/`, and
  `teleclaude/events/delivery/`. `teleclaude/core/integration/` is workflow's
  code-integration machinery; the package-ownership table in the context map
  is the authority for every root.
- **Maintenance stance:** see `project/spec/domain/glossary`. No replacement transport design is
  authored here.

### Ownership boundary

- **Owns:** provider and process transport, inbound normalization, outbound
  delivery mechanics, and translation across external boundaries.
- **Does not own:** session-input acceptance or execution, identity policy,
  todo lifecycle, or presentation policy merely because integration carries
  the message.
- **Published contracts:** normalized inbound commands and events, outbound
  delivery requests and results, and provider-neutral transport types.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
