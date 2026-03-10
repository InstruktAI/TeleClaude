---
description: 'Phase B state machine: build, review, fix, and finalize routing for implementation work.'
id: 'project/design/architecture/work-state-machine'
domain: 'software-development'
scope: 'project'
type: 'design'
---

# Work State Machine — Design

## Purpose

The Work state machine routes implementation through four sub-phases: **Build → Review → Fix → Finalize**. Unlike the Prepare machine which has an explicit phase enum, the Work machine derives its routing decision from the combination of `build` and `review` status fields in `state.yaml`.

**Entry point:** `telec todo work [slug]`
**Implementation:** [`next_work()`](../../../../teleclaude/core/next_machine/core.py)
**Terminal outputs:** `COMPLETE`, `NO_READY_ITEMS`, `HANDOFF` (to integration)

### Referenced files

| File | Purpose |
|------|---------|
| [`teleclaude/core/next_machine/core.py`](../../../../teleclaude/core/next_machine/core.py) | State machine implementation (`next_work()`) |
| [`docs/software-development/procedure/lifecycle/build.md`](../../../software-development/procedure/lifecycle/build.md) | Build procedure |
| [`docs/software-development/procedure/lifecycle/review.md`](../../../software-development/procedure/lifecycle/review.md) | Review procedure |
| [`docs/software-development/procedure/lifecycle/fix-review.md`](../../../software-development/procedure/lifecycle/fix-review.md) | Fix review procedure |
| [`docs/software-development/procedure/lifecycle/finalize.md`](../../../software-development/procedure/lifecycle/finalize.md) | Finalize procedure |
| [`docs/general/procedure/orchestration.md`](../../../general/procedure/orchestration.md) | Orchestration loop procedure |

### Referenced doc snippets

| Snippet ID | Content |
|------------|---------|
| `software-development/procedure/lifecycle/build` | Build phase — implement plan, commit per task |
| `software-development/procedure/lifecycle/review` | Review phase — parallel lanes, structured findings |
| `software-development/procedure/lifecycle/fix-review` | Fix phase — address findings, peer conversation |
| `software-development/procedure/lifecycle/finalize` | Finalize — two-stage: worker prepare, orchestrator apply |
| `general/procedure/orchestration` | Orchestration loop and dispatch rules |
| `software-development/policy/definition-of-done` | Quality gates for completion |
| `software-development/policy/testing` | Pre-commit quality gates |

## Inputs/Outputs

**Inputs:**

- `todos/{slug}/requirements.md` — feature requirements (from Phase A)
- `todos/{slug}/implementation-plan.md` — technical design with task checkboxes (from Phase A)
- `todos/{slug}/state.yaml` — build/review status, finalize state, review rounds
- `todos/{slug}/quality-checklist.md` — build and review gate checkboxes
- `todos/roadmap.yaml` — slug resolution and dependency graph
- Worktree at `trees/{slug}/` — isolated git branch for implementation

**Outputs:**

- Code changes, tests, and commits (build)
- `todos/{slug}/review-findings.md` — structured findings with severity and verdict (review)
- `todos/{slug}/deferrals.md` — out-of-scope work identified during build (optional)
- Integration handoff events (`branch.pushed`, `deployment.started`)
- Updated `state.yaml` with phase progression

### State YAML structure

```yaml
phase: in_progress              # pending | in_progress | done
build: pending                  # pending | started | complete
review: pending                 # pending | approved | changes_requested
deferrals_processed: false

finalize:
  status: pending               # pending | ready | handed_off
  branch: my-feature
  sha: abc123...
  ready_at: 2026-03-09T10:00:00+00:00
  worker_session_id: sess-xyz
  handed_off_at: null
  handoff_session_id: null

review_round: 0                 # counter for review iterations
max_review_rounds: 3            # limit (configurable)
review_baseline_commit: ""      # SHA for incremental review scope

unresolved_findings: []         # R1-F1, R1-F2, ...
resolved_findings: []           # R1-F1, R1-F2, ...
```

## Invariants

- **Routing from state**: all routing decisions derive from `build` and `review` fields in `state.yaml`. No internal state.
- **Build gates before review**: `make test` and `telec todo demo validate <slug>` must pass before dispatching a reviewer.
- **Artifact verification**: mechanical checks at phase boundaries (tasks checked, commits exist, findings substantive).
- **Stale approval guard**: if new commits exist between `review_baseline_commit` and current HEAD, the machine resets `review=pending` to force a fresh review.
- **Review round limit**: after `max_review_rounds` (default 3) iterations, the machine returns `REVIEW_ROUND_LIMIT` for orchestrator decision instead of looping.
- **Finalize serialization**: only one finalize may run at a time; the integration queue serializes delivery.
- **Stash prohibition**: git stash is forbidden in all agent workflows. The machine checks for stash debt.

## Primary flows

### State diagram

```mermaid
stateDiagram-v2
    [*] --> Preconditions

    state Preconditions {
        [*] --> SlugResolution
        SlugResolution --> DependencyCheck
        DependencyCheck --> WorktreeSetup
        WorktreeSetup --> CleanCheck
    }

    Preconditions --> Build: build = pending/started
    Preconditions --> Review: build = complete, review = pending
    Preconditions --> Fix: review = changes_requested
    Preconditions --> Finalize: review = approved

    Build --> Review: build gates pass
    Review --> Fix: verdict = REQUEST CHANGES
    Review --> Finalize: verdict = APPROVE
    Fix --> Review: fixes committed

    state Finalize {
        [*] --> CheckDeferrals
        CheckDeferrals --> FinalizeWorker: deferrals processed
        FinalizeWorker --> MarkReady: FINALIZE_READY
        MarkReady --> Handoff: emit integration events
    }

    Finalize --> [*]: HANDOFF to Phase C
```

### Routing logic

The machine reads `state.yaml` and routes based on `build` and `review` status:

```mermaid
flowchart TD
    Start(["telec todo work [slug]"])
    ReadState["Read state.yaml"]

    BuildCheck{"build status?"}
    ReviewCheck{"review status?"}
    FinalizeCheck{"finalize.status?"}

    DispatchBuild["Dispatch /next-build"]
    DispatchReview["Dispatch /next-review-build"]
    DispatchFix["Dispatch /next-fix-review"]
    DispatchDefer["Dispatch /next-defer"]
    DispatchFinalize["Dispatch /next-finalize"]
    Handoff["Emit integration events\nMark finalize=handed_off"]

    Start --> ReadState
    ReadState --> BuildCheck

    BuildCheck -->|"pending / started"| DispatchBuild
    BuildCheck -->|"complete"| ReviewCheck

    ReviewCheck -->|"pending"| DispatchReview
    ReviewCheck -->|"changes_requested"| DispatchFix
    ReviewCheck -->|"approved"| FinalizeCheck

    FinalizeCheck -->|"pending, has deferrals"| DispatchDefer
    FinalizeCheck -->|"pending, no deferrals"| DispatchFinalize
    FinalizeCheck -->|"ready"| Handoff
    FinalizeCheck -->|"handed_off"| Handoff
```

### Precondition checks

Before routing to any sub-phase, the Work machine runs these checks in order:

```mermaid
flowchart TD
    P1["1. Resolve slug\n(explicit or first ready item)"]
    P2["2. Dependency gating\n(all deps must be done)"]
    P3["3. Stash debt check\n(git stash forbidden)"]
    P4["4. Artifact existence\n(requirements.md + plan)"]
    P5["5. Preparation freshness\n(grounding must be valid)"]
    P6["6. Worktree management\n(ensure + prep + sync)"]
    P7["7. Clean check\n(uncommitted changes)"]
    P8["8. Claim item\n(pending -> in_progress)"]

    P1 --> P2 --> P3 --> P4 --> P5 --> P6 --> P7 --> P8
```

### Happy path (sequence diagram)

```mermaid
sequenceDiagram
    participant O as Orchestrator
    participant SM as Work Machine
    participant B as Builder Worker
    participant R as Reviewer Worker
    participant F as Finalizer Worker
    participant I as Integration Queue

    O->>SM: telec todo work slug
    SM-->>O: DISPATCH /next-build

    Note over O,B: Build Phase
    O->>B: telec sessions run --command /next-build --args slug
    B->>B: Implement tasks, write tests, commit per task
    B->>B: Check all tasks [x], make test, make lint
    B-->>O: BUILD COMPLETE: slug
    O->>O: telec todo mark-phase slug --build complete
    O->>O: telec sessions end builder-session

    O->>SM: telec todo work slug
    SM-->>O: DISPATCH /next-review-build

    Note over O,R: Review Phase
    O->>R: telec sessions run --command /next-review-build --args slug --mode slow
    R->>R: Run review lanes (code, tests, security, types, ...)
    R->>R: Write review-findings.md
    R-->>O: REVIEW COMPLETE: slug - Verdict: APPROVE
    O->>O: telec todo mark-phase slug --review approved
    O->>O: telec sessions end reviewer-session

    O->>SM: telec todo work slug
    SM-->>O: DISPATCH /next-finalize

    Note over O,F: Finalize Phase
    O->>F: telec sessions run --command /next-finalize --args slug
    F->>F: git fetch origin main, git merge origin/main
    F->>F: git push origin HEAD:slug
    F-->>O: FINALIZE_READY: slug
    O->>O: telec todo mark-finalize-ready slug
    O->>O: telec sessions end finalizer-session

    O->>SM: telec todo work slug
    SM-->>O: HANDOFF - emit integration events
    SM->>I: Enqueue (slug, branch, sha)
    Note over I: Phase C begins
```

### Review/fix loop (sequence diagram)

When the reviewer requests changes, the machine dispatches a fixer. The fixer and reviewer may communicate directly via peer conversation protocol.

```mermaid
sequenceDiagram
    participant O as Orchestrator
    participant SM as Work Machine
    participant R as Reviewer
    participant F as Fixer

    O->>SM: telec todo work slug
    SM-->>O: DISPATCH /next-review-build

    Note over O,F: Review Round 1
    O->>R: telec sessions run --command /next-review-build --args slug --mode slow
    R-->>O: Verdict: REQUEST CHANGES (3 findings)
    O->>O: telec todo mark-phase slug --review changes_requested
    O->>O: telec sessions end reviewer-session

    O->>SM: telec todo work slug
    SM-->>O: DISPATCH /next-fix-review

    Note over O,F: Fix Round 1
    O->>F: telec sessions run --command /next-fix-review --args slug
    Note over R,F: Peer conversation protocol:<br/>Fixer and Reviewer may DM<br/>each other via --direct link
    F-->>O: FIX COMPLETE: slug (3/3 addressed)
    O->>O: telec sessions end fixer-session

    O->>SM: telec todo work slug
    SM-->>O: DISPATCH /next-review-build

    Note over O,F: Review Round 2
    O->>R: telec sessions run --command /next-review-build --args slug --mode slow
    R-->>O: Verdict: APPROVE
    O->>O: telec todo mark-phase slug --review approved
```

### Command dispatch map

| Sub-Phase | Command | Worker Role | Thinking Mode | Output |
|-----------|---------|-------------|---------------|--------|
| Build | `/next-build` | Builder | `med` | Code, tests, commits |
| Build (bug) | `/next-bugs-fix` | Builder | `med` | Bug fix, investigation |
| Review | `/next-review-build` | Reviewer | `slow` (mandatory) | `review-findings.md`, verdict |
| Fix | `/next-fix-review` | Fixer | `med` | Fix commits |
| Deferrals | `/next-defer` | Orchestrator | — | New todos from deferrals |
| Finalize | `/next-finalize` | Finalizer | `med` | Branch pushed, FINALIZE_READY |

### Lifecycle events

| Event | Emitted When |
|-------|-------------|
| `build.started` | Builder worker dispatched |
| `build.complete` | Build phase marked complete |
| `review.started` | Reviewer worker dispatched |
| `review.approved` | Review verdict = APPROVE |
| `review.changes_requested` | Review verdict = REQUEST CHANGES |
| `branch.pushed` | Finalize worker pushed branch |
| `deployment.started` | Integration handoff initiated |

## Failure modes

- **No ready items in roadmap**: returns `NO_READY_ITEMS` — run prepare first.
- **Dependency not satisfied**: returns `BLOCKED` with dependency information.
- **Stash debt detected**: hard error — git stash is forbidden in agent workflows.
- **Missing preparation artifacts**: returns `NO_READY_ITEMS` — run `telec todo prepare` first.
- **Stale preparation grounding**: returns instruction to re-run prepare before building.
- **Worker crash**: orchestrator retries once, then escalates with context.
- **Review round limit exceeded**: returns `REVIEW_ROUND_LIMIT` for orchestrator decision — approve with documented follow-up for non-critical residual items, or escalate if unresolved critical findings remain.
- **Build gates fail**: re-dispatches builder to fix the issue before review.
- **State repair**: auto-repairs inconsistent state (e.g., `review=approved` + `build != complete` → repair to `build=complete`; `review=approved` with stale baseline → reset `review=pending`).
