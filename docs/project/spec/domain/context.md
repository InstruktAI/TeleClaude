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
<!-- planned:code-uc-blueprint-traceability -->
- **Implementation behavior map:**
  `docs/project/spec/feature/context/implementation-behavior-map.md` owns the
  function-level use-case declaration and Blueprint enrichment contract.
<!-- /planned:code-uc-blueprint-traceability -->
- **Implementation roots:** `teleclaude/context_selector.py`,
  `teleclaude/docs/`, `teleclaude/resource_validation/`, and distribution code
  under `teleclaude/install/`.
- **Maintenance stance:** see `project/spec/domain/glossary`. No replacement context architecture is
  authored here.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
