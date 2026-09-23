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
- **Also does not own:** the relationships those rules read. Which person a call
  resolves to, which companies that person belongs to, and which projects they
  are assigned to are resolved facts belonging to `identity`; which company owns
  a project is a declaration belonging to `config`. This context consumes both
  through their published contracts and restates neither.

**Resolved read scope** — for one caller, the set of documentation tiers in
reach paired with the depth each is read at. Depth is one of two values: a tier
the caller holds a declared relationship to is read in full, and a tier they
hold none to is read at whatever its snippets declare about themselves. The
scope is a property of the caller, never of the invocation's directory.
<!-- /planned:docs-tier-layering -->

- **Also owns:** the artifact-source registry — which exact files, uniform
  directory trees, and immediate package directories of a registered root are
  artifact-source boundaries, of which kind, at which tier, with which reach
  and authorship — and every decision taken from it: reach admission,
  composition of the domain-partitioned global command corpus and the
  mother-only skill catalog, project delivery, and retraction of what a run no
  longer produces. Implementation roots for this ownership are
  `teleclaude/agent_artifacts.py`, `teleclaude/artifact_ownership.py`,
  `teleclaude/global_skills.py`, and `scripts/distribute.py`.
- **Also does not own:** the publishing declaration that bounds reach (a
  `config` fact), any command's canonical name or emission (facts owned by the
  context that owns that command), or resolution of a name to a document at
  dispatch (an `agent_runtime` decision). This context consumes the first two
  through their published contracts and lays out the corpus the latter resolves.
- **Also publishes:** the registry as a typed contract every source
  consumer reads; its non-overlapping path classification distinguishes the
  authored global-skill catalog master from incorporated package directories.
  It also publishes the composed corpus laid out as `<domain>/<name>` and reach,
  collision, or unclassifiable-source findings that name the offending files.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
