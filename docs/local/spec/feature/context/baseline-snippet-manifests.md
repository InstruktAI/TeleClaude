---
description: 'Curated baseline.md files of @-refs that anchor the always-loaded snippet set per scope.'
visibility: 'public'
---

# Baseline Snippet Manifests — Spec

## Required reads

- @docs/local/spec/domain/context.md
- @docs/local/spec/feature/context/doc-selection-policy.md

## What it is

The global scope, each published domain, and each home's local half
(`docs/local/baseline.md`) can declare a curated "always-load" baseline set
of snippets via a `baseline.md` manifest. The manifest contains nothing but
`@`-refs to Source files — no prose, no frontmatter, no H1. The Selection
policy's `--baseline-only` mode reduces the visible Index to exactly the
snippets reachable from these manifests, giving callers a known minimum
context floor for any task. The global index also projects files under
`docs/global/baseline/<type>/` as catalog entries: their IDs use
`baseline/<type>/<path>`, their type comes from the directory, and their scope
is global. These files do not need taxonomy snippet frontmatter.

## Canonical fields

### Cross-context references

- None direct. The baseline manifest concept is wholly owned by the context
  bounded context; consumers (Selection policy, Index build, Sync) all live
  inside the same context boundary.

## Known caveats

- Baseline manifests do NOT enforce dependency closure. A manifest entry
  whose snippet declares Required reads will not auto-include those reads in
  the baseline-only set, so callers under `--baseline-only` get less context
  than they may expect.
- Taxonomy snippets derive `type` and `scope` from the path: `scope` from
  the home and half (a publisher's `docs/global/**`→global, a project's
  `docs/local/**`→project, either half of a person's or company's home→that
  tier) and `type` from the taxonomy folder; baseline catalog entries are a
  separate projection. Validation separately enforces that the H1 suffix
  matches the path-derived type. A taxonomy path that does not resolve to a
  derivable classification fails the index build with an error naming the file.
