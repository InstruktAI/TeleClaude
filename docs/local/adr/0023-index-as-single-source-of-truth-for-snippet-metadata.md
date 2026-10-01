---
date: '2026-06-10'
description: 'The per-project index derives id/type/scope/domain from the snippet path and is the single source of truth; frontmatter stops authoring these fields and consumers read only the index.'
number: '23'
visibility: 'public'
---

# ADR-0023: Index As Single Source Of Truth For Snippet Metadata — ADR

## Context

A doc snippet's `id`, `type`, `scope`, and `domain` are fully determined by its path and H1 suffix, yet every snippet also hand-authored these same fields in frontmatter — redundant copies of path-derived facts. The redundancy drifted (dozens of inconsistent authored `scope` values), and the fields were consumed inconsistently — most readers went through the index, but some paths read raw frontmatter, and the index build silently skipped snippets with missing classifier frontmatter, hiding the drift.

## Decision

The per-project index derives and materializes `id`, `type`, `scope`, and `domain` from the path, and is the single source of truth for them.

- `scope` collapses to `{global, project}`; `domain` is the id's first segment.
- Consumers read these fields ONLY from the index; the runtime recomputation paths are deleted rather than left as a third place the derivation rule lives.
- Frontmatter no longer authors `id`/`type`/`scope`/`domain`; validators derive classification pre-index via the same path-derivation primitive the index build uses.
- A path that does not resolve to a derivable classification fails the build loudly, replacing the old silent-skip.

## Consequences

- Single source of truth for classification; the authored-vs-derived drift surface is eliminated by construction.
- One behavioral change in selection: every `docs/global/**` snippet now resolves `scope: global`, making all global-tree snippets cross-project followable (previously domain-scoped ones were wrongly blocked).
- A corpus migration strips the now-derived fields from the existing files atomically with the deriver switch, so the index and corpus never disagree.

## Alternatives Considered

- **Keep frontmatter authoritative, add a lint to catch drift.** Rejected: it preserves two sources of truth, and the lint must encode the path-derivation rule, so the rule exists twice.
- **Derive in the index but leave the runtime recomputation functions.** Rejected: that is a third place the rule lives — the exact recomputation this decision removes.
