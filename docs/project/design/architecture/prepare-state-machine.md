---
description: 'Phase A state machine: sequential artifact production with review gates, from idea to implementation-ready.'
id: 'project/design/architecture/prepare-state-machine'
domain: 'software-development'
scope: 'project'
type: 'design'
---

# Prepare State Machine — Design

## Purpose

The Prepare state machine transforms a human's idea (`input.md`) into a set of reviewed, approved, and grounded artifacts ready for implementation. It enforces sequential artifact production with review gates between each step — no artifact is produced until its predecessor is approved.

**Entry point:** `telec todo prepare [slug]`
**Implementation:** [`PreparePhase`](../../../../teleclaude/core/next_machine/core.py) enum (10 states)
**Terminal states:** `PREPARED` (success), `BLOCKED` (failure)

### Referenced files

| File | Purpose |
|------|---------|
| [`teleclaude/core/next_machine/core.py`](../../../../teleclaude/core/next_machine/core.py) | State machine implementation (`PreparePhase` enum, `next_prepare()`) |
| [`docs/software-development/procedure/lifecycle/prepare.md`](../../../software-development/procedure/lifecycle/prepare.md) | Prepare procedure |
| [`docs/software-development/procedure/maintenance/next-prepare.md`](../../../software-development/procedure/maintenance/next-prepare.md) | Orchestration loop procedure |
| [`docs/software-development/procedure/maintenance/next-prepare-discovery.md`](../../../software-development/procedure/maintenance/next-prepare-discovery.md) | Discovery worker procedure |
| [`docs/software-development/procedure/maintenance/next-prepare-draft.md`](../../../software-development/procedure/maintenance/next-prepare-draft.md) | Plan drafting worker procedure |
| [`docs/software-development/procedure/maintenance/next-prepare-gate.md`](../../../software-development/procedure/maintenance/next-prepare-gate.md) | DOR gate worker procedure |

### Referenced doc snippets

| Snippet ID | Content |
|------------|---------|
| `software-development/procedure/lifecycle/prepare` | Prepare phase overview |
| `software-development/procedure/maintenance/next-prepare` | Orchestration loop |
| `software-development/procedure/maintenance/next-prepare-discovery` | Discovery worker |
| `software-development/procedure/maintenance/next-prepare-draft` | Draft worker |
| `software-development/procedure/maintenance/next-prepare-gate` | DOR gate worker |
| `software-development/procedure/lifecycle/review-requirements` | Requirements review |
| `software-development/procedure/lifecycle/review-plan` | Plan review |
| `software-development/policy/definition-of-ready` | DOR gates validated by gate phase |
| `software-development/policy/preparation-artifact-quality` | Quality rules for requirements and plans |

## Inputs/Outputs

**Inputs:**

- `todos/{slug}/input.md` — human idea or requirement (entry point)
- `todos/{slug}/state.yaml` — durable phase tracking, review verdicts, grounding metadata
- `todos/roadmap.yaml` — work item registry (slug resolution)

**Outputs:**

- `todos/{slug}/requirements.md` — triangulated, reviewed, approved requirements
- `todos/{slug}/implementation-plan.md` — review-aware, rationale-rich, reviewed, approved plan
- `todos/{slug}/demo.md` — draft demonstration plan
- `todos/{slug}/dor-report.md` — gate assessment
- `todos/{slug}/state.yaml` — updated with grounding metadata and DOR verdict
- `prepare.*` lifecycle events at each phase transition

| Artifact | Created by | Reviewed by |
|----------|-----------|-------------|
| `input.md` | Human (via `/next-refine-input`) | — |
| `requirements.md` | Discovery worker (`/next-prepare-discovery`) | Requirements reviewer (`/next-review-requirements`) |
| `implementation-plan.md` | Draft worker (`/next-prepare-draft`) | Plan reviewer (`/next-review-plan`) |
| `demo.md` | Draft worker | — |
| `dor-report.md` | Gate worker (`/next-prepare-gate`) | — |

## Invariants

- **Sequential gating**: no artifact is produced until its predecessor is reviewed and approved.
- **Phase derivation**: when no durable `prepare_phase` exists in `state.yaml`, the machine derives the current phase from artifact existence on disk.
- **Review round limits**: both requirements and plan reviews are capped at `DEFAULT_MAX_REVIEW_ROUNDS` (3). Exceeding the limit transitions to `BLOCKED`.
- **Grounding freshness**: preparation is only valid if referenced files and input digest have not changed since grounding. Stale preparation triggers re-grounding.
- **Idempotent re-entry**: `telec todo prepare` is safe to call at any time — first call creates, subsequent calls verify and heal.
- **Container detection**: if the draft worker splits a todo into children, the machine treats the parent as a container and only child slugs proceed to Phase B.

## Primary flows

### State diagram

```mermaid
stateDiagram-v2
    [*] --> INPUT_ASSESSMENT

    INPUT_ASSESSMENT --> TRIANGULATION: requirements.md missing
    INPUT_ASSESSMENT --> REQUIREMENTS_REVIEW: requirements.md exists

    TRIANGULATION --> REQUIREMENTS_REVIEW: requirements drafted

    REQUIREMENTS_REVIEW --> PLAN_DRAFTING: verdict = approve
    REQUIREMENTS_REVIEW --> TRIANGULATION: verdict = needs_work (re-draft)
    REQUIREMENTS_REVIEW --> BLOCKED: review rounds exceeded

    PLAN_DRAFTING --> PLAN_REVIEW: plan drafted

    PLAN_REVIEW --> GATE: verdict = approve
    PLAN_REVIEW --> PLAN_DRAFTING: verdict = needs_work (re-draft)
    PLAN_REVIEW --> BLOCKED: review rounds exceeded

    GATE --> GROUNDING_CHECK: DOR score >= 8

    GROUNDING_CHECK --> PREPARED: grounding valid
    GROUNDING_CHECK --> RE_GROUNDING: grounding stale

    RE_GROUNDING --> PLAN_REVIEW: plan updated, needs fresh review

    PREPARED --> [*]
    BLOCKED --> [*]
```

### States reference

| State | Description | Agent Action | Auto-advance |
|-------|-------------|-------------|--------------|
| `INPUT_ASSESSMENT` | Evaluate input.md, check if requirements.md exists | No | Yes — routes to TRIANGULATION or REQUIREMENTS_REVIEW |
| `TRIANGULATION` | Requirements need to be written or reworked | Yes — dispatch `/next-prepare-discovery` | No |
| `REQUIREMENTS_REVIEW` | Requirements exist, need review verdict | Yes — dispatch `/next-review-requirements` | No |
| `PLAN_DRAFTING` | Requirements approved, plan needs to be written | Yes — dispatch `/next-prepare-draft` | No |
| `PLAN_REVIEW` | Plan exists, needs review verdict | Yes — dispatch `/next-review-plan` | No |
| `GATE` | All artifacts exist and approved, run DOR validation | Yes — dispatch `/next-prepare-gate` | No |
| `GROUNDING_CHECK` | Verify freshness of artifacts against current codebase | No | Yes — routes to PREPARED or RE_GROUNDING |
| `RE_GROUNDING` | Referenced files changed since grounding, plan must update | Yes — dispatch `/next-prepare-draft` | No |
| `PREPARED` | Terminal success — todo is ready for Phase B (Work) | No | — |
| `BLOCKED` | Terminal failure — human intervention needed | No | — |

### Flow diagram

```mermaid
flowchart TD
    Start(["telec todo prepare [slug]"])

    DerivePhase{"Durable phase\nin state.yaml?"}
    Derive["Derive phase from\nartifact existence"]

    InputAssess{"requirements.md\nexists?"}

    Triangulate["Dispatch\nnext-prepare-discovery"]
    ReqExists{"requirements_review\nverdict?"}
    DispatchReqReview["Dispatch\nnext-review-requirements"]

    CheckRounds1{"Review rounds\n< max (3)?"}

    PlanExists{"implementation-plan.md\nexists?"}
    DispatchDraft["Dispatch\nnext-prepare-draft"]

    PlanReview{"plan_review\nverdict?"}
    DispatchPlanReview["Dispatch\nnext-review-plan"]
    CheckRounds2{"Review rounds\n< max (3)?"}

    Gate{"DOR score\n>= 8?"}
    DispatchGate["Dispatch\nnext-prepare-gate"]

    GroundingCheck{"Grounding\nfresh?"}
    ReGround["Dispatch\nnext-prepare-draft\n(with diff)"]

    Prepared(["PREPARED"])
    Blocked(["BLOCKED"])

    Start --> DerivePhase
    DerivePhase -->|"No"| Derive
    DerivePhase -->|"Yes"| InputAssess
    Derive --> InputAssess

    InputAssess -->|"No"| Triangulate
    InputAssess -->|"Yes"| ReqExists
    Triangulate --> ReqExists

    ReqExists -->|"No verdict"| DispatchReqReview
    DispatchReqReview --> ReqExists
    ReqExists -->|"approve"| PlanExists
    ReqExists -->|"needs_work"| CheckRounds1
    CheckRounds1 -->|"Yes"| Triangulate
    CheckRounds1 -->|"No"| Blocked

    PlanExists -->|"No"| DispatchDraft
    PlanExists -->|"Yes"| PlanReview
    DispatchDraft --> PlanReview

    PlanReview -->|"No verdict"| DispatchPlanReview
    DispatchPlanReview --> PlanReview
    PlanReview -->|"approve"| Gate
    PlanReview -->|"needs_work"| CheckRounds2
    CheckRounds2 -->|"Yes"| DispatchDraft
    CheckRounds2 -->|"No"| Blocked

    Gate -->|"score >= 8"| GroundingCheck
    Gate -->|"not assessed"| DispatchGate
    DispatchGate --> Gate

    GroundingCheck -->|"fresh"| Prepared
    GroundingCheck -->|"stale"| ReGround
    ReGround --> PlanReview
```

### Orchestrator loop (sequence diagram)

The orchestrator calls `telec todo prepare slug` in a loop. Each call returns an instruction block. The orchestrator dispatches the requested worker, waits for the notification, then calls again.

```mermaid
sequenceDiagram
    participant O as Orchestrator
    participant SM as Prepare Machine
    participant D as Discovery Worker
    participant RR as Requirements Reviewer
    participant DR as Draft Worker
    participant PR as Plan Reviewer
    participant G as Gate Worker

    Note over O,G: Phase 1 — Discovery
    O->>SM: telec todo prepare slug
    SM-->>O: DISPATCH next-prepare-discovery
    O->>D: telec sessions run --command /next-prepare-discovery --args slug
    D-->>O: notification (requirements.md written)
    O->>SM: telec todo prepare slug

    Note over O,G: Phase 2 — Requirements Review
    SM-->>O: DISPATCH next-review-requirements
    O->>RR: telec sessions run --command /next-review-requirements --args slug
    RR-->>O: notification (verdict: approve)
    O->>SM: telec todo prepare slug

    Note over O,G: Phase 3 — Plan Drafting
    SM-->>O: DISPATCH next-prepare-draft
    O->>DR: telec sessions run --command /next-prepare-draft --args slug
    DR-->>O: notification (implementation-plan.md written)
    O->>SM: telec todo prepare slug

    Note over O,G: Phase 4 — Plan Review
    SM-->>O: DISPATCH next-review-plan
    O->>PR: telec sessions run --command /next-review-plan --args slug
    PR-->>O: notification (verdict: approve)
    O->>SM: telec todo prepare slug

    Note over O,G: Phase 5 — DOR Gate
    SM-->>O: DISPATCH next-prepare-gate
    O->>G: telec sessions run --command /next-prepare-gate --args slug
    G-->>O: notification (DOR score >= 8)
    O->>SM: telec todo prepare slug

    Note over O,G: Phase 6 — Grounding Check (mechanical)
    SM-->>O: PREPARED
    Note over O: Todo ready for Phase B
```

### Command dispatch map

Each state dispatches a specific worker command via `telec sessions run`:

| State | Command | Worker Role | Thinking Mode | Output Artifact |
|-------|---------|-------------|---------------|-----------------|
| `TRIANGULATION` | `/next-prepare-discovery` | Architect | `slow` | `requirements.md` |
| `REQUIREMENTS_REVIEW` | `/next-review-requirements` | Reviewer | `slow` | verdict in `state.yaml` |
| `PLAN_DRAFTING` | `/next-prepare-draft` | Architect | `slow` | `implementation-plan.md`, `demo.md` |
| `PLAN_REVIEW` | `/next-review-plan` | Reviewer | `slow` | verdict in `state.yaml` |
| `GATE` | `/next-prepare-gate` | Assessor | `slow` | `dor-report.md`, DOR score in `state.yaml` |
| `RE_GROUNDING` | `/next-prepare-draft` | Architect | `slow` | Updated `implementation-plan.md` |

### Grounding system

Grounding tracks whether the preparation artifacts are still valid relative to the current codebase. It is checked as the final step before declaring PREPARED.

```mermaid
flowchart LR
    subgraph "Grounding Metadata (state.yaml)"
        Valid["grounding.valid"]
        BaseSHA["grounding.base_sha"]
        InputDigest["grounding.input_digest"]
        RefPaths["grounding.referenced_paths"]
    end

    subgraph "Staleness Checks"
        C1{"input.md digest\nchanged?"}
        C2{"Referenced files\nchanged since\nbase_sha?"}
    end

    Valid --> C1
    Valid --> C2
    C1 -->|"Yes"| Stale["RE_GROUNDING\n(invalidated)"]
    C2 -->|"Yes"| Stale
    C1 -->|"No"| C2
    C2 -->|"No"| Fresh["PREPARED\n(grounding valid)"]
```

Invalidation triggers:
- `input.md` SHA-256 digest changed since last grounding
- Files referenced in the implementation plan changed since `base_sha`
- External automation detects file path overlap after an integration delivery (`telec todo prepare --invalidate-check`)

### Lifecycle events

| Event | Emitted When |
|-------|-------------|
| `prepare.input_refined` | Input refined by human |
| `prepare.discovery_started` | Discovery worker dispatched |
| `prepare.requirements_drafted` | `requirements.md` written |
| `prepare.requirements_approved` | Requirements review verdict = approve |
| `prepare.plan_drafted` | `implementation-plan.md` written |
| `prepare.plan_approved` | Plan review verdict = approve |
| `prepare.grounding_invalidated` | Grounding check found stale artifacts |
| `prepare.regrounded` | Re-grounding completed, plan updated |
| `prepare.completed` | Terminal PREPARED state reached |
| `prepare.blocked` | Terminal BLOCKED state reached |

## Failure modes

- **Missing `input.md`**: BLOCKED — human must provide input via `/next-refine-input`.
- **Review round limit exceeded**: BLOCKED after 3 rounds — escalate to human with accumulated findings.
- **Discovery worker crash**: orchestrator retries once, then BLOCKED with error context.
- **Grounding never stabilizes**: each re-grounding triggers a fresh plan review. Persistent churn means the codebase is changing faster than the plan can track — manual intervention needed.
- **Superseded todo**: BLOCKED — todo has been replaced by another work item.
- **Container split**: draft worker splits scope into children. Machine detects via `breakdown.todos` and treats the parent as a container — only children proceed to Phase B.
