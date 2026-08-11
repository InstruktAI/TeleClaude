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

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
