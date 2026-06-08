---
id: 'project/adr/0015-kind-as-lifecycle-entry-point'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'A kind names the lifecycle entry point: the SDLC kinds (feature/change/bug), the non-SDLC `task` kind, and an optional kind at intake (kind-less dumps are classified by /analyze-todo-input).'
date: '2026-06-06'
adr_status: 'accepted'
number: '15'
---

# Kind as Lifecycle Entry Point — ADR

## Context

The todo `kind` vocabulary had drifted to seven values (feature, refactor,
migration, bug, todo, prepped, draft) across four layers, with the CLI silently
ignoring kind and `kind=None` coercing to "todo". Several values were not routing
decisions: `todo` carried no signal; `refactor`/`migration` routed identically to
a generic change; `prepped` was evidence (a plan already exists), not a work
category; `draft` was a state (parked). Separately, the prepare/work procedures
were PRD-centric and treated a missing PRD as a legacy defect, so no-PRD work drew
spurious "missing PRD" findings and burned review rounds.

## Decision

A `kind` names the work-unit's **entry point** into the lifecycle. Three are
SDLC kinds — the work ends in a code change:

- `feature` → intake (authors a PRD)
- `change` → plan drafting (no PRD; intent is the `input` artifact)
- `bug` → fix lane (no PRD, no upfront plan)

A fourth, `task`, is **not** SDLC: a fuzzy but actionable unit an agent performs
directly, whose work need not touch the codebase (send a notification, hit an API
on a schedule, run an operation, spin off other todos). It has no
PRD/plan/build/review/integrate lane; it is created silent (never auto-dispatched);
and its actionable, living bookkeeping is a `task-plan` artifact the agent grooms
as it works — ticking off steps and appending results in the durable artifact, not
in an ephemeral session.

Routing for the SDLC kinds is the single table `KIND_ENTRY_PHASE` in
`core/next_machine/kinds.py`; the prepare/plan/fast-track frozensets are
projections of it. A kind is normalized on every read via `canonical_kind()`.

**Kind is optional at the human-intake boundary.** A kind-less creation stores
the raw brain dump as the `input` artifact and routes to `/analyze-todo-input`,
which interprets it and **proposes** a kind for human approval — writing a
`task-plan` when it proposes `task`, or recording an SDLC proposal with a
one-line rationale so the normal lane can take over after approval. The
classification step proposes and never executes, so unframed human intent is
never acted on unprompted. Kind is unset through this pre-approval window; once
the human approves the proposal through `telec todo stamp --kind-approved`, it
is fixed and normalized like any other. This relaxes the prior
"kind mandatory at every input boundary" rule to "mandatory once classified."

The evicted values become orthogonal inputs/state, not kinds:

- `prepped` → `--plan` creation input (supply a complete plan → build).
- `draft` → `--silent` (create without dispatch) / freeze-icebox (parked).
- `refactor`/`migration`/`chore`/`todo` → all map to `change`.

All no-PRD intent (including the bug report) lives in the universal `input`
artifact; the dedicated `bug` artifact is retired. The "approved intent artifact"
concept (`prd` for feature, `input` for change/bug) replaces hard-coded PRD
references so no-PRD work is first-class.

## Consequences

- One routing source of truth; membership-set drift is structurally impossible
  because the sets derive from one map.
- Rows with legacy kinds normalize on read and heal on next write; a one-time
  on-open migration renames `bug` artifacts to `input`.
- v1 is transitional and carries no unit tests for this change (per the testing
  policy); behavior is covered by functional/smoke verification.
- v2 (Rust, inactive) was rewritten to the same kinds.
- A kind-less intake path now exists; the only auto-pickup it triggers is
  classification (`/analyze-todo-input`), which proposes a kind but never executes
  — preserving the guarantee that agents do not act on raw human intent unprompted.
- `task` introduces a non-SDLC terminal: a todo can complete by doing an action
  and grooming its `task-plan`, with no `delivery_commit`. The "no `delivered`
  without `delivery_commit`" invariant is SDLC-scoped; a task's evidence trail is
  its groomed `task-plan` (and any result it records).
- New artifacts: `task-plan` (the actionable + bookkeeping artifact for `task`).
  `input` stays immutable; analyze only reads it.
- The "kind fixed at creation" invariant becomes "fixed once assigned": a
  kind-less todo's kind is proposed by analyze and assigned exactly once by
  human approval through the stamp boundary.
- A `change` carries no PRD/PO intent gate but a **mandatory doc-snippet
  reflection obligation**. Because the change lane skips the PRD — where the
  doc-first "snippets to author or update" deliverable otherwise lives — the
  plan-draft step owns identifying and authoring the affected pending snippets,
  and the plan-review documentation lane hard-gates it (with an explicit
  `doc_impact_none: <reason>` escape, mirroring `architecture_skipped`). This is
  what makes it safe for a `change` to bypass PO oversight: it may skip intent
  review, but it cannot silently drift documented behavior.

## Alternatives Considered

- Keep `chore`/`refactor`/`migration` as human-facing labels mapping to one
  route: rejected — kinds exist only for routing; non-routing distinctions belong
  to commit types (commitizen), not the kind axis.
- Keep `prepped`/`draft` as kinds: rejected — they are evidence and state, not
  entry points.
- Overload `implementation-plan` as the `task` actionable artifact: rejected —
  it is a code-change artifact. A task's heterogeneous steps (direct actions +
  spawned todos + waits) get their own `task-plan`; the code artifact stays
  code-only.
- Make `task` a general/business-domain kind stored company-wide
  (`~/.teleclaude/todos.db`): rejected for now — todos are project/repo-scoped,
  so `task` stays in the existing kind system. Cross-domain, company-wide intake
  is a later layer that slots above the per-project analyze step, not a carve-out
  now.
- Supersede this ADR with a new one: rejected — the kind model is being extended
  (a 4th kind, an optional-kind boundary), not reversed. 0015 remains the single
  kind-model record and is amended in place.
