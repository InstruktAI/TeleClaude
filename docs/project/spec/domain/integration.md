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
- **Maintenance stance:** see `project/spec/domain/glossary`. No replacement transport design is
  authored here.

### Ownership boundary

- **Owns:** provider and process transport, inbound normalization, outbound
  delivery mechanics, and translation across external boundaries.
- **Does not own:** session-input acceptance or execution, identity policy,
  todo lifecycle, or presentation policy merely because integration carries
  the message.
<!-- planned-change:external-session-identity -->
- **Published contracts:** normalized inbound commands and events, outbound
  delivery requests and results, and provider-neutral transport types.
<!-- change:external-session-identity -->
- **Published contracts:** normalized inbound commands and events, outbound
  delivery requests and results, provider-neutral transport types, and the
  attested-caller signal — the kernel-held peer identity of the process on the
  other end of a local connection, normalized at connection-accept and supplied
  to identity. Integration carries that evidence and never interprets it: which
  session owns the process is agent_runtime's answer, and what the caller is
  authorized to do is identity's.
<!-- /planned-change:external-session-identity -->

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
