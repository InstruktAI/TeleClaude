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

<!-- planned:docs-tier-layering -->
- **Also owns:** the resolved read scope — which documentation tiers a caller
  may reach, how deeply each is read, and the authorization of the selectors
  that name a tier explicitly. These are rules about documentation reach, so
  they resolve here rather than to the contexts that supply their inputs.
- **Also does not own:** the relationships those rules read. Which companies a
  person belongs to, which projects they are assigned to, and which company owns
  a project are declarations belonging to `config`; which person a call resolves
  to belongs to `identity`. This context consumes all four through their
  published contracts and restates none of them.

**Resolved read scope** — for one caller, the set of documentation tiers in
reach paired with the depth each is read at. Depth is one of two values: a tier
the caller holds a declared relationship to is read in full, and a tier they
hold none to is read at whatever its snippets declare about themselves. The
scope is a property of the caller, never of the invocation's directory.
<!-- /planned:docs-tier-layering -->

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
