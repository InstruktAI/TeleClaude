---
id: project/design/architecture-v2/docs-authority
type: design
scope: project
domain: software-development
description: v2 docs-authority design for serialized docs writes, delivered-by reconciliation, file watching, and sync triggering inside the context service.
delivered_by: [integrate-deliveredby-flip]
---

# Docs Authority — Design

## Purpose

The docs authority is the v2 `context` service responsibility that serializes
structural writes to `docs/`, runs delivery-time `delivered_by`
reconciliation for workflow callers, watches docs source files, and triggers
context sync. It is not a separate bounded context or a ninth service. It is
the write authority inside the existing `context` service so every lifecycle
caller mutates docs through one filesystem boundary.

## Inputs/Outputs

Inputs:

- lifecycle requests from workflow and integration that need structural docs
  mutations
- authored docs source changes under `docs/`
- file-system watch events for externally edited docs
- manual `telec sync` / `telec context sync` invocations as an escape hatch

Outputs:

- rewritten docs source files
- exact pathspecs staged for the caller's commit boundary
- success or failure returned synchronously to the caller
- rebuilt docs indexes and deployed context outputs after sync

## Invariants

- Context is the sole writer for structural `docs/` mutations.
- Lifecycle callers do not open `docs/**/*.md` directly; they call the docs
  authority and handle its success or failure.
- Writes are serialized per working tree so concurrent lifecycle calls cannot
  interleave frontmatter edits.
- Delivery reconciliation is scoped to the candidate slug before any write is
  performed, so unrelated stale snippet flips never ride along with a delivery.
- File watching distinguishes authority-owned writes from external edits and
  suppresses the authority's own next event for the touched path.
- Manual sync remains available for CI, recovery, and explicit operator force.

## Primary flows

### Delivery reconciliation

1. Workflow integration calls the context docs-authority operation with the
   delivered candidate slug, the integration worktree path, and a roadmap
   status snapshot where the candidate slug is already treated as delivered.
2. The authority applies that lifecycle decision and reconciles only snippets
   whose `delivered_by` contains the candidate slug.
3. The authority writes the affected snippet frontmatter and stages the exact
   paths in the caller's worktree.
4. The authority returns success or a typed failure. The caller either commits
   the staged paths with the delivery or refuses the operation.

### External file edit

1. The watcher observes a `docs/` source change that was not written by the
   authority.
2. The authority debounces related edits.
3. When the debounce expires, context validates snippets, rebuilds indexes,
   and distributes deployed artifacts.

### Serialized structural write

1. Multiple lifecycle callers request docs mutations.
2. The authority queues them against the working tree.
3. Each write runs to success or failure before the next write starts.
4. The caller owns retry, blocking, or user-facing recovery policy.

### v1 replacement path

The v2 authority replaces three inline v1 implementation slices over time:
`removal-snippet-frontmatter-sync`, `integrate-deliveredby-flip`, and the
future rename `delivered_by` substitution. Cutover replaces each local
parse/write/stage sequence with a context authority call.

## Failure modes

- If validation fails before a write, the authority returns failure and writes
  nothing.
- If a path is dirty from a non-authority edit, the authority refuses that
  write rather than overwriting user work.
- If staging fails, the authority returns failure with the path and git
  diagnostic; the caller does not continue to its commit prompt.
- If sync fails after an external edit, the authority reports the sync failure
  and leaves source files unchanged.
- If concurrent callers contend, queue order is deterministic; callers see
  success or failure for their own request only.
