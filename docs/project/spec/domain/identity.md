---
visibility: internal
description: Frozen v1 ownership anchor for caller identity resolution and authentication evidence.
---

# Identity Domain Spec — Spec

## What it is

The v1 identity area resolves local people, machines, terminals, and sessions
into caller identity used by CLI and API boundaries. It describes current
appliance behavior only; the replacement identity and access model lives in
TeleClaudeNext.

## Canonical fields

- **Current behavior:** `docs/project/spec/feature/identity/` and the auth
  feature specs that require this anchor.
- **Implementation roots:** `teleclaude/core/identity.py`,
  `teleclaude/session_identity.py`, `teleclaude/api/auth.py`, and
  `teleclaude/cli/telec/auth.py`.

- **Maintenance stance:** see `project/spec/domain/glossary`. New tenancy, RBAC, and secrets
  architecture belongs to TeleClaudeNext.

### Ownership boundary

- **Owns:** principal resolution, authentication evidence, and the identity
  facts authorization decisions consume.
- **Also owns:** organizational relationship resolution — what a person's
  company membership, company role, and project assignment mean, and what
  resolving them reports. The declarations themselves are config's; identity
  reads them and reinterprets nothing.
- **Also owns:** person-context binding resolution — whether a person
  workspace's declared identity claim is accepted as binding that context to
  exactly one registered person, validated against the person registry, with
  unknown, ambiguous, and disagreeing claims failing closed. The declaration
  itself is config's; identity reads it and reinterprets nothing, and an
  accepted binding is an identity fact that grants no authority of its own.
  The behavioral contract is
  `project/spec/feature/identity/person-context-binding`.
- **Does not own:** provider payload parsing, message delivery, session action,
  or workflow transitions merely because they carry a principal.
- **Published contracts:** resolved-principal and authentication-evidence types
  consumed at CLI, API, integration, and runtime boundaries.

<!-- planned:procedure-event-activation -->
- **Also owns:** the session company context that tools running inside a
  session read — the company, the origin (human-directed work with its human
  principal, or system-principal company work), and whether the company is
  resolved, absent, or ambiguous. The company is the session record's company
  when `agent_runtime` has set one; otherwise, for a human-lineage session
  whose person has exactly one eligible company, that company as resolved;
  otherwise unresolved, naming the eligible companies when several remain.
  Identity resolves it when a tool asks, from the session record that the
  session identity document's session id names and from its own membership
  resolution, and publishes it through `telec auth whoami`. The company lives
  on the session record alone: identity writes none of it into the session
  identity document, so no copy can disagree with the record, and the answer
  survives a restart because the record does. Readers consume the published
  answer and never re-validate it.
<!-- /planned:procedure-event-activation -->

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
