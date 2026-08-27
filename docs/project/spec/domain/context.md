---
visibility: internal
description: Frozen v1 ownership anchor for file-based documentation, agent assets, deployment, and context selection.
---

# Context Domain Spec — Spec

## What it is

The v1 context area owns file-based documentation and agent assets, their
validation and deployment, and the selection of context supplied to agent
sessions. This repository carries only the current appliance contract;
replacement architecture is authoritative only in TeleClaudeNext.

## Canonical fields

- **Current behavior:** the documentation and agent-artifact policies plus
  feature specs that require this anchor.
- **Implementation roots:** `teleclaude/context_selector.py`,
  `teleclaude/docs/`, `teleclaude/resource_validation/`, and distribution code
  under `teleclaude/install/`.
- **Maintenance stance:** see `project/spec/domain/glossary`. No replacement context architecture is
  authored here.

### Ownership boundary

- **Owns:** file-based documentation and agent-artifact validation,
  publication, deployment, and selection of context supplied to sessions.
- **Does not own:** the domain behavior described by published documents or the
  runtime decisions agents make after context is supplied.
- **Published contracts:** validated snippet and artifact packages, publication
  indexes, and context-selection results.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
