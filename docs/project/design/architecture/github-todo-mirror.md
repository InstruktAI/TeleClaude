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
visible and diffable on GitHub. It is a single-owner, read-only projection: the local todo
store remains the source of truth, nothing flows back from GitHub, and the projection is
derived entirely from local truth. Collaborative / multi-contributor reflection is out of
scope; the projection is shaped (id-scoped, forward-only) so that capability can be added
later without rework.

## Inputs/Outputs

Inputs:

- The per-project **`github.enabled`** toggle — the entire enablement decision, set by the
  owner of the repo. There is no auto-detection, capability probe, or prompt.
- `workflow.todo.*` domain events (`created`, `phase_advanced`, `delivered`, `updated`,
  `renamed`) delivered through the daemon's system event pipeline.
- Local todo truth read at projection time (status, kind, lifecycle phase, hold, delivered
  commit, dependency edges, group/children).
- The GitHub origin, resolved live from `git remote get-url origin` at projection time.
- The machine's existing `gh` authentication (scopes `repo` + `project`).
- A rebuildable cache of GitHub-generated identifiers (board node id, field option ids,
  id→issue map).

Outputs (when enabled):

- An Issue per todo carrying the todo's immutable `roadmap.id` as a hidden marker, with
  open/closed state from status (active/icebox → open; delivered → closed-completed; removed
  → closed-not-planned).
- A Projects v2 board item per issue with fields: Kind, Phase, Hold, Delivered SHA.
- Native blocked-by dependency edges and sub-issue parent relationships reconciled to the
  local set.

No new authoritative local state; the only addition is the rebuildable id cache.

## Invariants

- **Mirror, never authority.** Local is the sole source of truth; the projection is
  outbound-only; there is no inbound GitHub→local sync.
- **Enabled by toggle.** `github.enabled` is the whole enablement decision. The owner sets it
  for a repo they own; there is no detection, clean-slate probe, capability gate, or prompt.
- **Never touch foreign state; id-scoped and forward-only.** The projector only ever
  creates/updates Issues bearing its own marker, keyed on the todo's immutable `roadmap.id`,
  and writes only to its own marker-stamped board — so enabling it over a repo that already
  has Issues never clobbers them. Reconciliation is **forward-only**: it asserts each local
  todo's Issue and never removes an Issue merely because no local todo matches it; it never
  treats the board as "must equal my todos, delete the rest." This is the clobber-safety in
  single-owner scope and the shape that keeps non-colliding multi-contributor reflection
  open later (each contributor touches only its own ids; the marker labels authorship).
- **Convergent and idempotent.** Each projection asserts a todo's complete desired GitHub
  state from current local truth; applying it twice is a no-op. Graph relations are
  read-then-reconciled to the local set; an "already exists" rejection is already-converged.
- **Off the hot path, failures isolated.** Projection runs in the event pipeline, never
  inside a todo mutation. The mirror catches every projection error internally and returns
  normally — it never raises — so the pipeline's retry/dead-letter machinery never fires on a
  GitHub failure and GitHub health is never coupled into event processing. A GitHub outage,
  rate-limit, or revoked token never fails, blocks, or slows a `telec todo` mutation.
  Reconciliation is the only re-attempt path; the mirror is eventually consistent.
- **Self-describing identity.** The `roadmap.id` (a UUID) is stamped into each issue body as a
  hidden HTML-comment marker, invisible when rendered; the local→GitHub map is reconstructible
  by scanning markers. The id cache is an accelerator only, never authoritative.
- **Slug rename preserves linkage.** The projector keys on the immutable `roadmap.id`, never
  the slug; a rename updates the existing Issue in place and never creates a duplicate.

## Primary flows

### 1. Per-todo projection (event-driven)

```mermaid
sequenceDiagram
    participant DB as Todo store (local truth)
    participant Bus as System event pipeline
    participant Mirror as Mirror projector
    participant GH as GitHub (gh)
    DB->>Bus: workflow.todo.* (created/phase_advanced/delivered/updated/renamed)
    Bus->>Mirror: deliver event (off the mutation hot path)
    Mirror->>Mirror: github.enabled? resolve live origin? else inert
    Mirror->>DB: read this todo's complete current truth
    Mirror->>GH: upsert Issue (roadmap.id marker, title, open/closed state)
    Mirror->>GH: upsert board item + fields (Kind, Phase, Hold, Delivered SHA)
    Mirror->>GH: read current blocked-by + sub-issue edges; reconcile to local set
```

The mirror projector is a processor in the daemon's system event pipeline — a sibling of the
lifecycle router — reacting to `workflow.todo.*` events. It reads the affected todo's complete
current truth from the local store and asserts the corresponding GitHub state keyed on
`roadmap.id`; it never derives state from the event payload alone, so out-of-order or
duplicate delivery converges to the same result.

### 2. Reconciliation (on-demand, optionally scheduled)

A `telec` command runs the same forward-only projection over every local todo in a project —
the integrity audit and self-heal. Contract: `telec projects mirror-reconcile [--project
<path>]` (conforms to the `telec projects` namespace; resolves the project from cwd when
omitted), idempotent, `github.enabled`-gated, reporting converged-vs-repaired counts. It never
removes Issues it does not recognize.

### 3. Tooling prerequisite check (`make install`)

`make install` verifies the machine's `gh` authentication carries the scopes the mirror needs
— `repo` and `project` — and, for any missing scope, prints the exact remediation
(`gh auth refresh -s <missing>`) instead of failing silently. The mirror reuses the existing
`gh` login and adds no new credential surface.

## Failure modes

- **GitHub outage or rate-limit.** The per-event projection fails; the mirror catches it
  internally and returns normally (it never raises), so the pipeline's retry/DLQ never fires
  and no local mutation is affected. Reconciliation re-converges on its next run.
- **Token scope lost.** Projection fails and surfaces through the mirror's health/status; never
  a hot-path failure, never silent GitHub corruption.
- **Partial projection.** The next projection re-asserts the complete desired state;
  idempotency and edge set-reconciliation make the re-run safe.
- **Issues the projector did not create, or does not recognize.** Never touched — the projector
  only acts on Issues whose `roadmap.id` is in the local store, and reconciliation never removes
  unrecognized Issues.
- **Stale or lost id cache.** Rebuilt by scanning issue markers; the cache is never the source
  of truth.

## See Also

- docs/project/adr/0054-v1-is-the-system.md
