---
date: '2026-06-06'
description: 'A kind names the lifecycle entry point: the SDLC kinds (feature/change/bug), the non-SDLC `task` kind, and an optional kind at intake (kind-less dumps are classified and auto-assigned by /analyze-todo-input).'
number: '15'
visibility: 'public'
---

# ADR-0015: Kind as Lifecycle Entry Point — ADR

## Context

The todo `kind` vocabulary had drifted to seven values across four layers, with the CLI silently ignoring kind. Several values were not routing decisions: `todo` carried no signal; `refactor`/`migration` routed identically to a generic change; `prepped` was evidence (a plan exists); `draft` was a parked state. Separately, the prepare/work procedures were PRD-centric and treated a missing PRD as a defect, so no-PRD work drew spurious findings.

## Decision

A `kind` names the work-unit's **entry point** into the lifecycle.

- Three **SDLC** kinds end in a code change: `feature` → intake (authors a PRD); `change` → plan drafting (no PRD; intent is the `input` artifact); `bug` → fix lane (no PRD, no upfront plan).
- A fourth, `task`, is **not** SDLC: an actionable unit an agent performs directly, whose work need not touch the codebase. It has no PRD/plan/build/review/integrate lane, is created silent, and its bookkeeping is a durable `task-plan` artifact the agent grooms as it works.

**Kind is optional at intake, and classification is autonomous.** A kind-less creation stores the raw dump as `input` and routes to `/analyze-todo-input`, which interprets it and **assigns** a kind directly — no proposal, no human approval gate. The absence of a kind is itself the "awaiting classification" signal. This relaxes "kind mandatory at every input boundary" to "mandatory once classified." The analyzer classifies and routes; it does not execute the work — so unframed intent is routed into a lane, never acted on, without a human gate in the way.

The evicted values become orthogonal inputs/state, not kinds: a complete-plan supply, a silent/parked creation, and `refactor`/`migration`/`chore`/`todo` all mapping to `change`. All no-PRD intent lives in the universal `input` artifact; the dedicated `bug` artifact is retired, and "approved intent artifact" (PRD for feature, `input` for change/bug) replaces hard-coded PRD references.

## Consequences

- One routing source of truth; kind-set drift is structurally impossible.
- Legacy kinds normalize on read and heal on next write.
- `task` introduces a non-SDLC terminal: a todo can complete by doing an action and grooming its `task-plan`, with no delivery commit. The "no delivered without delivery-commit" invariant is SDLC-scoped.
- A `change` carries no PRD/PO intent gate but a **mandatory doc-snippet reflection obligation**: the plan-draft step identifies and authors the affected pending snippets and the plan-review documentation lane hard-gates it (with a `doc_impact_none` escape). This is what makes it safe for a `change` to skip PO oversight — it may skip intent review, but cannot silently drift documented behavior.

## Alternatives Considered

- **Keep `chore`/`refactor`/`migration` as labels mapping to one route.** Rejected: kinds exist only for routing; non-routing distinctions belong to commit types, not the kind axis.
- **Keep `prepped`/`draft` as kinds.** Rejected: they are evidence and state, not entry points.
- **Make `task` a company-wide kind.** Rejected for now: todos are project-scoped; cross-domain intake is a later layer above the per-project analyze step.
- **Classification as a propose-then-human-approve gate.** Rejected: it put a human approval step in front of a pure routing decision, stranding kind-less todos in limbo and contradicting the platform's autonomy. Classification auto-assigns and routes; the human redirects after the fact.
