---
description: Single-owner outbound reflection of a project's todos into its own GitHub repository as Issues plus a Projects v2 board, gated by a per-project toggle and kept convergent via id-scoped, forward-only projection.
visibility: internal
delivered_by:
  - github-todo-mirror
---

# GitHub Todo Mirror — Design

## Purpose

When enabled for a project, the mirror reflects that project's todo/roadmap state into the
project's own GitHub repository — as Issues plus a Projects v2 board — so roadmap state is
visible and diffable on GitHub. It is a single-owner, read-only projection: the centralized
workflow store remains the source of truth, nothing flows back from GitHub, and the projection
is derived entirely from that store's truth. Collaborative / multi-contributor reflection is out
of scope; the projection is shaped (id-scoped, forward-only) so that capability can be added
later without rework.

## Inputs/Outputs

Inputs:

- The per-project **`github.enabled`** toggle — the operator's enablement decision, set by the
  owner of the repo. There is no auto-detection, capability probe, or prompt.
- `workflow.todo.*` mutation events (`created`, `phase_advanced`, `delivered`, `updated`,
  `renamed`) emitted at the centralized workflow write boundary (see
  `project/spec/domain/workflow#workflowtodo-events`), delivered asynchronously to the projector
  downstream of that write-path seam.
- Todo truth read at projection time from the centralized workflow store (status, kind,
  lifecycle phase, hold, delivered commit, dependency edges, group/children), scoped to the
  todo's owning `project` row (see
  `project/design/architecture/database#todo-store-distribution`).
- The project's GitHub origin, taken from the `ProjectRef`-resolved `project` row's origin
  metadata and classified through the git-transport regime (see
  `project/spec/domain/workflow#project-identity-projectref`) — never a re-probed inline
  `git remote get-url origin`.
- The machine's existing `gh` authentication (scopes `repo` + `project`).
- A rebuildable cache of GitHub-generated identifiers (board node id, field option ids,
  id→issue map).

Outputs (when eligible):

- An Issue per todo carrying the todo's immutable id as a hidden marker, with open/closed state
  from status (active/icebox → open; delivered → closed-completed; removed → closed-not-planned).
- A Projects v2 board item per issue with fields: Kind, Phase, Hold, Delivered SHA.
- Native blocked-by dependency edges and sub-issue parent relationships reconciled to the
  local set.

No new authoritative local state; the only addition is the rebuildable id cache.

## Invariants

- **Mirror, never authority.** The centralized workflow store is the sole source of truth; the
  projection is outbound-only; there is no inbound GitHub→local sync.
- **Enabled by toggle, gated by the remote regime.** `github.enabled` is the operator's whole
  enablement decision — there is no detection, clean-slate probe, capability gate, or prompt.
  Effective eligibility is that toggle AND the project being remote-backed with a GitHub origin,
  resolved once through the distributed regime seams: the `ProjectRef`-resolved `project` row
  supplies identity and origin, and the git-transport gateway classifies remote-backed vs
  local-only. A local-only or non-GitHub project is inert — the mirror reuses the regime decision
  rather than re-probing the origin inline, so no "does a remote exist?" check is scattered into
  the projector.
- **Project-scoped projection.** Each projection resolves the todo's owning `project` row first,
  reads only the todos belonging to that project, and mirrors them to that row's GitHub origin
  and board. The `(project_id, slug)` natural key — not an implicit per-database boundary —
  defines membership.
- **Never touch foreign state; id-scoped and forward-only.** The projector only ever
  creates/updates Issues bearing its own marker, keyed on the todo's immutable id, and writes
  only to its own marker-stamped board — so enabling it over a repo that already has Issues never
  clobbers them. Reconciliation is **forward-only**: it asserts each todo's Issue and never
  removes an Issue merely because no todo matches it; it never treats the board as "must equal my
  todos, delete the rest." This is the clobber-safety in single-owner scope and the shape that
  keeps non-colliding multi-contributor reflection open later (each contributor touches only its
  own ids; the marker labels authorship).
- **Convergent and idempotent.** Each projection asserts a todo's complete desired GitHub state
  from current store truth; applying it twice is a no-op. Graph relations are read-then-reconciled
  to the local set; an "already exists" rejection is already-converged.
- **Off the hot path, failures isolated.** Projection runs asynchronously downstream of the
  workflow write boundary, never inside a todo mutation. The mirror catches every projection
  error internally and returns normally — it never raises — so the delivery mechanism's
  retry/dead-letter machinery never fires on a GitHub failure and GitHub health is never coupled
  into the write path. A GitHub outage, rate-limit, or revoked token never fails, blocks, or
  slows a `telec todo` mutation. Reconciliation is the only re-attempt path; the mirror is
  eventually consistent.
- **Self-describing identity.** The todo's immutable id is stamped into each issue body as a
  hidden HTML-comment marker, invisible when rendered; the store→GitHub map is reconstructible by
  scanning markers. The id cache is an accelerator only, never authoritative.
- **Slug rename preserves linkage.** The projector keys on the immutable id, never the mutable
  slug; a rename updates the existing Issue in place and never creates a duplicate.

## Primary flows

### 1. Per-todo projection (event-driven)

```mermaid
sequenceDiagram
    participant Store as Centralized workflow store
    participant Write as Workflow write boundary
    participant Mirror as Mirror projector
    participant GH as GitHub (gh)
    Store->>Write: todo mutation committed
    Write->>Mirror: workflow.todo.* delivered async (off the write hot path)
    Mirror->>Mirror: resolve project row; eligible? (github.enabled + remote-backed GitHub via regime) else inert
    Mirror->>Store: read this todo's complete current truth, scoped to its project
    Mirror->>GH: upsert Issue (immutable-id marker, title, open/closed state)
    Mirror->>GH: upsert board item + fields (Kind, Phase, Hold, Delivered SHA)
    Mirror->>GH: read current blocked-by + sub-issue edges; reconcile to local set
```

The mutation hook is grounded at the centralized workflow write boundary: every committed todo
mutation emits the `workflow.todo.*` contract, and the projection is scheduled from that emission
regardless of which daemon delivery mechanism carries it. A daemon pipeline consumer is only the
async delivery path downstream of the write boundary — not the seam the mirror depends on. On
delivery the projector resolves the todo's `project` row, confirms eligibility through the regime
seams, reads the affected todo's complete current truth from the centralized store (project-
scoped), and asserts the corresponding GitHub state keyed on the todo's immutable id; it never
derives state from the event payload alone, so out-of-order or duplicate delivery converges to
the same result.

### 2. Reconciliation (on-demand, optionally scheduled)

A `telec` command runs the same forward-only projection over every todo in a project — the
integrity audit and self-heal. Contract: `telec projects mirror-reconcile [--project <path>]`
(conforms to the `telec projects` namespace; resolves the project from cwd when omitted),
idempotent, eligibility-gated, reporting converged-vs-repaired counts. It resolves the `project`
row, sweeps only that project's todos, and never removes Issues it does not recognize.

### 3. Tooling prerequisite check (`make install`)

`make install` verifies the machine's `gh` authentication carries the scopes the mirror needs —
`repo` and `project` — and, for any missing scope, prints the exact remediation
(`gh auth refresh -s <missing>`) instead of failing silently. The mirror reuses the existing
`gh` login and adds no new credential surface.

## Failure modes

- **GitHub outage or rate-limit.** The per-event projection fails; the mirror catches it
  internally and returns normally (it never raises), so the delivery mechanism's retry/DLQ never
  fires and no todo mutation is affected. Reconciliation re-converges on its next run.
- **Token scope lost.** Projection fails and surfaces through the mirror's health/status; never a
  write-path failure, never silent GitHub corruption.
- **Partial projection.** The next projection re-asserts the complete desired state; idempotency
  and edge set-reconciliation make the re-run safe.
- **Project not eligible (local-only or non-GitHub origin).** The regime classifies it inert; the
  projector performs no GitHub work and creates no GitHub-side state.
- **Issues the projector did not create, or does not recognize.** Never touched — the projector
  only acts on Issues whose immutable-id marker resolves to a todo in the centralized store, and
  reconciliation never removes unrecognized Issues.
- **Stale or lost id cache.** Rebuilt by scanning issue markers; the cache is never the source of
  truth.

## See Also

- docs/project/adr/0054-v1-is-the-system.md
- docs/project/design/architecture/database.md
- docs/project/spec/domain/workflow.md
