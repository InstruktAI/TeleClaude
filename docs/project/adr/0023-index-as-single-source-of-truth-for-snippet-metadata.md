---
id: 'project/adr/0023-index-as-single-source-of-truth-for-snippet-metadata'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '23'
date: '2026-06-10'
adr_status: 'accepted'
delivered_by:
  - index-leading-snippet-metadata
description: 'The per-project index derives id/type/scope/domain from the snippet path and is the single source of truth; frontmatter stops authoring these fields and consumers read only the index.'
---

# Index As Single Source Of Truth For Snippet Metadata — ADR

## Context

A doc snippet's `id`, `type`, `scope`, and `domain` are fully determined by its
path: `id` is the path under the docs tree, `scope` follows the source tree
(`docs/global/**`→global, `docs/project/**`→project), `domain` is the id's first
segment, and `type` is the H1 suffix. Yet every snippet also hand-authored these
same fields in frontmatter — redundant copies of path-derived facts.

The redundancy drifted. Authored `scope` had ~77 inconsistent values (including
malformed entries and the legacy `domain` scope value); authored classifiers
diverged from what the path implied. The fields were also consumed
inconsistently: most readers go through the index, but AGENTS.md generation and
the frontmatter validators read raw frontmatter. There was no single source of
truth, and the index build silently skipped snippets whose classifier
frontmatter was missing — hiding the drift instead of surfacing it.

## Decision

The per-project index derives and materializes `id`, `type`, `scope`, and
`domain` from the path, and is the single source of truth for them.

- `scope` collapses to `{global, project}` (the legacy `domain` scope value is
  dropped); `domain` is the id's first segment (`general | <domain> | project`).
- Consumers read these fields ONLY from the index. The runtime recomputation
  functions `_output_scope` and `_domain_for_snippet` in `context_selector` are
  deleted; the index values are read straight through.
- Frontmatter no longer authors `id`/`type`/`scope`/`domain`. Third-party docs
  drop `type: third-party`.
- Validators run pre-index, so they derive classification via a shared
  path-derivation primitive (the same primitive the index build uses) rather
  than reading frontmatter.
- A path that does not resolve to a derivable classification FAILS the build
  loudly, replacing the old silent-skip behavior.

Awareness tradeoff (accepted): classification is read from the path plus the H1
type-suffix, not from frontmatter. The runtime-emitted `scope`/`domain` therefore
change from today's degenerate authored values to correct path-derived ones.

## Consequences

- Single source of truth for snippet classification; the drift surface (authored
  vs. derived) is eliminated by construction.
- One behavioral consequence in selection: every `docs/global/**` snippet now
  resolves `scope: global`, making all global-tree snippets cross-project
  followable in `context_selector`'s required-reads follow. Previously
  domain-scoped snippets were wrongly blocked from that follow.
- A corpus migration strips the now-derived fields from ~491 files atomically
  with the deriver switch, so no window exists where the index and the corpus
  disagree.

## Alternatives Considered

- **Keep frontmatter authoritative, add a lint to catch drift.** Rejected: it
  preserves two sources of truth and only narrows the drift window; the lint
  itself must encode the path-derivation rule, so the rule exists twice.
- **Derive in the index but leave the runtime recomputation functions.** Rejected:
  `_output_scope`/`_domain_for_snippet` re-deriving at read time is a third place
  the rule lives and is the exact recomputation this decision removes.
