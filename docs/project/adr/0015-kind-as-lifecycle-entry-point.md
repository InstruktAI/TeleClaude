---
id: 'project/adr/0015-kind-as-lifecycle-entry-point'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Collapse todo kinds to feature/change/bug — a kind names the lifecycle entry point, not a work category.'
date: '2026-06-05'
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

A `kind` names exactly one thing: the work-unit's **entry point** into the
lifecycle. There are three:

- `feature` → intake (authors a PRD)
- `change` → plan drafting (no PRD; intent is the `input` artifact)
- `bug` → fix lane (no PRD, no upfront plan)

Routing is the single table `KIND_ENTRY_PHASE` in `core/next_machine/kinds.py`;
the prepare/plan/fast-track frozensets are projections of it. `kind` is mandatory
at every input boundary and normalized on every read via `canonical_kind()`.

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
- v2 (Rust, inactive) was rewritten to the same three kinds.

## Alternatives Considered

- Keep `chore`/`refactor`/`migration` as human-facing labels mapping to one
  route: rejected — kinds exist only for routing; non-routing distinctions belong
  to commit types (commitizen), not the kind axis.
- Keep `prepped`/`draft` as kinds: rejected — they are evidence and state, not
  entry points.
