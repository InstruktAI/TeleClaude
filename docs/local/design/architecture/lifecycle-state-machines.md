---
description: 'Overview of the three state machines that drive the TeleClaude software development lifecycle.'
visibility: 'public'
---

# Lifecycle State Machines — Design

## Purpose

TeleClaude's software development lifecycle is driven by three deterministic state machines, each governing a distinct phase of delivery. The orchestrator calls a machine, executes the returned instruction (typically dispatching a worker session), then calls again. This loop continues until a terminal state.

| Phase | Name                                      | State Machine                    | Entry Point                   | Purpose                                             |
| ----- | ----------------------------------------- | -------------------------------- | ----------------------------- | --------------------------------------------------- |
| **A** | [Prepare](prepare-flow.md)                | `lifecycle_phase` (prepare lane) | `telec todo prepare [slug]`   | Define PRD, architecture, and implementation plan   |
| **B** | [Work](work-state-machine.md)             | `lifecycle_phase` (work lane)    | `telec todo work [slug]`      | Build, review, fix, and finalize the implementation |
| **C** | [Integrate](integration-state-machine.md) | `IntegrationPhase` (12 states)   | `telec todo integrate [slug]` | Merge to main, push, deliver                        |

### Referenced files

| File                                                                                                       | Purpose                                     |
| ---------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| [`teleclaude/core/next_machine/core.py`](../../../../teleclaude/core/next_machine/core.py)                 | Prepare + Work state machine implementation |
| [`teleclaude/core/integration/state_machine.py`](../../../../teleclaude/core/integration/state_machine.py) | Integration state machine implementation    |

| [`teleclaude/core/integration/candidate_scan.py`](../../../../teleclaude/core/integration/candidate_scan.py) | FIFO candidate discovery by worktree-state scan |

| [`teleclaude/core/integration/lease.py`](../../../../teleclaude/core/integration/lease.py) | Singleton lease for integration serialization |

### Referenced doc snippets

| Snippet ID                                                | Content                                     |
| --------------------------------------------------------- | ------------------------------------------- |
| `sdlc/procedure/lifecycle-overview`                       | Full lifecycle phases and handoffs          |
| `general/procedure/orchestration`                         | Orchestration loop and dispatch rules       |
| `local/projects/teleclaude/spec/integration-orchestrator` | Integration contract (events, lease, queue) |

## Inputs/Outputs

**Inputs:**

`telec todo artifacts list {slug}` shows the following artifacts:

- `input` — human idea or requirement (Phase A entry)
- `prd` — product contract (Phase A output, Phase B input)
- `architecture` — optional thin index/log of the architecture doc-snippet edits (Phase A output, Phase B input)
- `implementation-plan` — technical design (Phase A output, Phase B input)

**Outputs:**

- Instruction blocks for the orchestrator to execute (dispatch worker, mark phase, handoff)
- Lifecycle events at each phase transition (consumed by automation and notifications)
- Delivered code on canonical `main` (Phase C pushes from integration worktree)
- Delivery bookkeeping (todo list updates and cleanup)

## Invariants

- **Deterministic routing**: given the same persisted evidence and `lifecycle_phase`, the same instruction is produced.
- **Sequential phases**: Prepare → Work → Integrate. No phase skipping.
- **Artifact immutability**: machines never modify artifacts directly; they delegate to workers.
- **Dependency blocking**: cannot claim a work item until all its dependencies are complete.
- **Integration serialization**: only one integrator pushes `main` at a time, enforced by a singleton lease.

- **One orchestrator per todo on a computer**: every start of a lifecycle orchestrator for a todo — a session create door or a lifecycle operation adopting its caller — passes its live-holder check and the creation or claim it admits inside one in-process critical section per project and todo, whatever its lane, so at most one live orchestrator holds the todo. The section records nothing; the session registry and `active_runner` remain the ownership facts (`local/projects/teleclaude/adr/0133-concurrent-driver-starts-serialize-in-process-at-the-start-doors`, `local/projects/teleclaude/adr/0134-a-colliding-driver-start-is-refused-without-waiting`).

- **One orchestrator per todo across computers**: for a project on the GitHub workflow store, the project names one active computer in a variable on its GitHub repository, set only by a deliberate `telec projects active-computer set`. Only that computer admits an orchestrator start of a todo, one at a time, and records the claim before the session is created or claimed; a start on any other computer is refused naming the active computer. Each computer answers for the sessions it runs, as drivers of one todo: a claimed session holds the todo while it is open, not closing, and drives that todo, or while a start of it for that todo is inside its computer's admission section. The active computer judges a claim by asking every computer the platform knows, and a claim stays held until the computer running its session shows it no longer drives the todo, or every computer answers that the session is not its own. Only the active computer writes the claim, inside its section for the todo: other computers ask it to release a claim for a session they ran, from inside their own section for the todo and holding it until the release is answered or its deadline has passed, and its lifecycle runner passes clear claims it judges ended. Making another computer active leaves a running orchestrator's claim with its session's computer until it ends. Reactivating a removed todo restores the claim its removal set aside. A start that finds the todo held is refused naming the holding session and the computer running it, or the computers that did not answer. A caller waits for an admission only within a bounded budget; a start still undecided when it expires is refused and creates nothing, and a claim recorded for it is cleared by the active computer.

- **Crash recovery**: all three machines are re-entrant. Re-calling after a crash resumes from durable state.

## Primary flows

### End-to-end flow

```mermaid
flowchart LR
    subgraph "Phase A — Prepare"
        Input["input"] --> Intake["Intake<br/>PRD"]
        Intake --> PRDReview["PRD<br/>Review"]
        PRDReview --> Architecture["Architecture<br/>(or skip)"]
        Architecture --> PlanDraft["Plan<br/>Drafting"]
        PlanDraft --> PlanReview["Plan<br/>Review"]
        PlanReview --> Gate["DOR<br/>Gate"]
        Gate --> Grounding["Grounding<br/>Check"]
    end

    subgraph "Phase B — Work"
        Build --> Review
        Review -->|"changes requested"| Fix
        Fix --> Review
        Review -->|"approved"| Finalize
    end

    subgraph "Phase C — Integrate"
        Queue["FIFO Queue"] --> Merge["Squash<br/>Merge"]
        Merge --> Push["Push to<br/>main"]
        Push --> Cleanup
    end

    Grounding -->|"PREPARED"| Build
    Finalize -->|"handoff"| Queue
    Cleanup -->|"delivered"| Done["Done"]
```

### How the machines connect

The orchestrator drives each machine in a loop. Phase boundaries are event-driven handoffs — Phase B emits integration readiness events that Phase C consumes via a durable queue.

```mermaid
sequenceDiagram
    participant Human
    participant Orchestrator
    participant Prepare as Phase A<br/>Prepare Machine
    participant Work as Phase B<br/>Work Machine
    participant Integrate as Phase C<br/>Integration Machine

    Human->>Orchestrator: input.md (idea, requirement)

    loop Until PREPARED
        Orchestrator->>Prepare: telec todo prepare [slug]
        Prepare-->>Orchestrator: instruction (dispatch worker)
        Note over Orchestrator: Dispatches intake, architecture,<br/>diagnose (bug), plan, review, or gate workers
    end
    Prepare-->>Orchestrator: PREPARED

    loop Until lifecycle_phase=finalize_ready
        Orchestrator->>Work: telec todo work [slug]
        Work-->>Orchestrator: instruction (dispatch worker)
        Note over Orchestrator: Dispatches builder, reviewer,<br/>fixer, or finalizer workers
    end
    Work-->>Orchestrator: FINALIZE_READY (TodosDb chokepoint emits integration event)

    loop Until queue drained
        Orchestrator->>Integrate: telec todo integrate
        Integrate-->>Orchestrator: instruction (merge/commit/push)
        Note over Integrate: Lease-serialized,<br/>crash-recoverable
    end
    Integrate-->>Orchestrator: COMPLETED
    Orchestrator-->>Human: Delivered
```

### Roles and responsibilities

The orchestrator never makes routing decisions — the machines own sequencing. The orchestrator dispatches what is requested.

```mermaid
flowchart TB
    subgraph Orchestrator["Orchestrator (Loop Driver)"]
        direction TB
        O1["Calls state machines"]
        O2["Dispatches worker sessions"]
        O3["Monitors worker output"]
        O4["Marks phase transitions"]
        O5["Owns session lifecycle"]
    end

    subgraph Workers["Workers (Execution)"]
        direction TB
        W1["Intake Agent — PRD"]
        W2["Architecture / plan agents"]
        W3["Review Agent — findings + verdict"]
        W4["Builder Agent — code + tests"]
        W5["Fixer Agent — address findings"]
        W6["Finalizer Agent — branch prep"]
    end

    subgraph Machines["State Machines (Routing)"]
        direction TB
        M1["Prepare — what to do next"]
        M2["Work — build/review/fix routing"]
        M3["Integrate — merge/push/cleanup"]
    end

    Orchestrator -->|"calls"| Machines
    Machines -->|"instructions"| Orchestrator
    Orchestrator -->|"dispatches"| Workers
    Workers -->|"notifications"| Orchestrator
```

### Worker dispatch pattern

Workers are dispatched via `telec sessions run`. The machine names the procedure;
the procedure's `dispatch` declaration supplies the agent preference and thinking
mode, and an explicit caller mode overrides it
(`local/projects/teleclaude/spec/feature/agent_runtime/role-aware-agent-dispatch`).
The prepare orchestrator performs intake, architecture and planning in its own
session; the sessions below are the ones a machine dispatches.

| Phase    | Worker Role    | Command                                                                                                                                               |
| -------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Prepare  | Diagnoser      | `sdlc/procedure/lifecycle/prepare/diagnose-peer` (bug)                                                                                                |
| Prepare  | Drift Analyzer | `sdlc/procedure/lifecycle/prepare/drift-analyze`                                                                                                      |
| Prepare  | Reviewer       | `sdlc/procedure/lifecycle/prepare/review-prd`, `sdlc/procedure/lifecycle/prepare/review-architecture`, `sdlc/procedure/lifecycle/prepare/review-plan` |
| Build    | Builder        | `sdlc/procedure/lifecycle/work/build` (all kinds, incl. bug)                                                                                          |
| Review   | Reviewer       | `sdlc/procedure/lifecycle/work/review-build`                                                                                                          |
| Fix      | Fixer          | _(no dispatch — the orchestrator relays the review-findings artifact to the existing builder session)_                                                |
| Finalize | Finalizer      | `sdlc/procedure/lifecycle/work/finalize`                                                                                                              |

### Detailed documentation

Each state machine has its own design document with full state diagrams, sequence diagrams, flow diagrams, and command cross-references:

1. **[Prepare Flow](prepare-flow.md)** — Phase A: PRD → Architecture → Plan, from idea to implementation-ready artifacts
2. **[Work State Machine](work-state-machine.md)** — Phase B: Build/review/fix/finalize routing with quality gates
3. **[Integration State Machine](integration-state-machine.md)** — Phase C: 12 states, lease-serialized merge-to-main delivery

## Failure modes

- **No todo list**: cannot discover work items. Returns error instructing user to create a todo.
- **Dependency cycle**: circular dependencies detected. Logs error, refuses to dispatch.
- **All agents unavailable**: hard error. If some are degraded, notes in guidance and lets orchestrator decide.
- **Worker crash**: orchestrator retries once, then escalates.
- **Phase mark failure**: worker must commit before marking phase.
- **Integration contention**: serialized by lease; concurrent candidates are queued in FIFO order.

- **Concurrent orchestrator starts**: orchestrator starts of one todo on one computer are decided one at a time; the first creates or claims the orchestrator and each later one is refused naming it. A start that arrives while another is being decided does not wait; it is refused as busy, naming the session being started.

- **Orchestrator stranded in initializing**: an orchestrator session counts as the todo's holder from its creation, so one whose bootstrap failed keeps holding the todo until it is ended; the bootstrap failure is published for a person to act on.

- **Holder's computer does not answer**: while the computer running a claimed session, or any computer when none answers for it, does not answer the active computer, the claim stays held and a start of that todo is refused naming the session and the computer running it, or the computers that did not answer; the todo can be started again once the claim is shown ended.
- **No active computer to admit a start**: while the project names no active computer, or its variable cannot be read from GitHub, every start of a GitHub-backed todo is refused naming why and creates nothing, and lifecycle runner passes skip those todos; no computer decides the start by its own registry instead.
- **Admission answered but the start failed**: a start that cannot create or claim its session after asking — refused, out of budget, or interrupted by its computer's restart — creates nothing; a claim recorded for it is cleared by the start's release request or by the active computer's next runner pass, once the session's computer answers that it does not drive the todo — whether or not the session is still open — or every computer answers that the session is not its own.
- **Release does not reach the active computer**: a claim for a session that ended on another computer stays held until the active computer's next runner pass judges it ended; while it is unreachable the claim stays held.
- **Removal while a driver runs on another computer**: a removal that a caller forces sets the todo's claim aside; reactivating the todo restores it, so the active computer judges it before admitting a start.
- **Computer on an older release**: a computer that does not run cross-computer admission still judges claims by its own registry and can start a second orchestrator until it is updated; one that still asks the fleet's master to admit its starts is refused by every computer but the active one.

- **Stale artifacts**: PRD or architecture updated but downstream artifacts not regenerated. Grounding check catches and triggers re-grounding.
- **Stale artifacts**: PRD or architecture updated but downstream artifacts not regenerated. Grounding check catches and triggers re-grounding.

## See Also

- docs/local/adr/0142-one-active-computer-per-github-backed-project.md — why one active computer admits starts and writes claims.
