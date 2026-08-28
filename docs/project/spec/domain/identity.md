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

<!-- planned:external-session-identity -->
- **Cross-cutting design:** `docs/project/design/architecture/local-caller-attestation.md`
  carries the transport-boundary and establishment design for callers without a
  TeleClaude pane.
<!-- /planned:external-session-identity -->
- **Maintenance stance:** see `project/spec/domain/glossary`. New tenancy, RBAC, and secrets
  architecture belongs to TeleClaudeNext.

### Ownership boundary

<!-- planned-change:external-session-identity -->
- **Owns:** principal resolution, authentication evidence, and the identity
  facts authorization decisions consume.
<!-- change:external-session-identity -->
- **Owns:** principal resolution, authentication evidence, the local peer
  attestation that authenticates a caller with no pane on TeleClaude's own tmux
  server, the session binding an externally hosted session establishes from that
  attestation, and the identity facts authorization decisions consume.
<!-- /planned-change:external-session-identity -->
- **Does not own:** provider payload parsing, message delivery, session action,
  or workflow transitions merely because they carry a principal.
- **Published contracts:** resolved-principal and authentication-evidence types
  consumed at CLI, API, integration, and runtime boundaries.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
