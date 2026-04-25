---
id: 'software-development/procedure/lifecycle/prepare/overview'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Prepare stage overview. Orchestrator drives the pair through discovery, artifact production, human approval, gate, and grounding.'
---

# Prepare Overview — Procedure

## Required reads

- @~/.teleclaude/docs/general/concept/agent-characteristics.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discovery.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/plan-draft.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/readiness-gate.md

## Goal

Drive the prepare state machine by calling `telec todo prepare [slug]` in a loop.
The machine dispatches a persistent pair of workers who explore the problem
together and then produce artifacts in turns. The orchestrator dispatches what
the machine requests and supervises the pair.

Produce reviewed, human-approved, and grounded preparation artifacts for a todo.

## Preconditions

1. `todos.db` roadmap exists and is readable.
2. Target slug is active (not icebox, not delivered) when slug is provided.

## Steps

### 1. Enter the state machine

Call `telec todo prepare [slug]`. Read the returned instruction block.

### 2. Execute the instruction

The state machine returns a linear script for the current state. The
orchestrator executes it verbatim and then calls `telec todo prepare [slug]`
again. The orchestrator never makes routing decisions — the machine owns
sequencing.

### The prepare flow

#### Full workflow

```mermaid
sequenceDiagram
    participant H as Human
    participant O as Orchestrator
    participant A as Worker A (intent)
    participant B as Worker B (rigor)

    Note over H,O: Work package handoff
    H->>O: todo with input (brain dump, existing artifacts, any starting state)

    rect rgb(240, 248, 255)
    Note over O,B: 1. DISPATCH — both workers receive the work package
    O->>A: telec sessions run (work package)
    O->>B: telec sessions run (work package)
    end

    rect rgb(245, 245, 220)
    Note over A,B: 2. INDEPENDENT INTAKE — each worker grounds alone
    A->>A: read input, codebase, roadmap, domain docs
    A->>A: form independent understanding
    B->>B: read input, codebase, roadmap, domain docs
    B->>B: form independent understanding
    A-->>O: agent_stop (intake done)
    B-->>O: agent_stop (intake done)
    end

    rect rgb(230, 255, 230)
    Note over O,B: 3. LINK — orchestrator connects the pair
    O->>A: telec sessions send A --direct (links A↔B)
    Note over A,B: Direct conversation established
    end

    rect rgb(255, 240, 245)
    Note over A,B: 4. DISCOVERY — pair-based, no roles
    A<<->>B: discuss, challenge, surface assumptions
    A<<->>B: check against codebase reality
    A<<->>B: resolve unknowns, converge on understanding
    A-->>O: agent_stop
    B-->>O: agent_stop
    Note over O: Read tails of both → assess convergence
    end

    rect rgb(240, 240, 255)
    Note over O,B: 5. REQUIREMENTS — turn-based (write then review)
    O->>A: "Write requirements based on your discussion."
    Note over B: B is not messaged — observes via direct link
    A->>A: writes requirements.md
    A-->>O: agent_stop
    O->>B: "A has written requirements. Review: did A capture everything?"
    B->>B: reviews for completeness and accuracy
    alt needs_work
        B-->>O: needs_work (findings)
        O->>A: "Fix forward: [findings]"
        A->>A: fixes requirements
        A-->>O: agent_stop
        O->>B: "Review again."
        B->>B: re-reviews
    end
    B-->>O: approve
    end

    rect rgb(255, 255, 220)
    Note over H,B: 6. HUMAN INTERJECTION — fix-forward refinement
    O-->>H: "Requirements ready for your review."
    H->>A: feedback, corrections (pair still in direct mode)
    Note over A,B: Both see human input via direct link, can contribute
    A->>A: updates requirements per human feedback
    Note over O: Orchestrator tails conversation
    O-->>H: "Stamp approved?"
    H-->>O: approved
    O->>O: stamps requirements approved
    end

    rect rgb(240, 240, 255)
    Note over O,B: 7. TEST SPECS — turn-based (write then review)
    O->>A: "Write test specifications."
    Note over B: B observes via direct link, does not respond
    A->>A: writes xfail specs from approved requirements
    A-->>O: agent_stop
    O->>B: "Review specs."
    alt needs_work
        B-->>O: needs_work
        O->>A: "Fix forward: [findings]"
        A-->>O: agent_stop
        O->>B: "Review again."
    end
    B-->>O: approve
    end

    rect rgb(240, 240, 255)
    Note over O,B: 8. IMPLEMENTATION PLAN — turn-based (roles flip)
    O->>B: "Write implementation plan."
    Note over A: A observes via direct link, does not respond
    B->>B: writes plan from requirements + specs
    B-->>O: agent_stop
    O->>A: "Review plan."
    alt needs_work
        A-->>O: needs_work
        O->>B: "Fix forward: [findings]"
        B-->>O: agent_stop
        O->>A: "Review again."
    end
    A-->>O: approve
    end

    rect rgb(240, 248, 255)
    Note over O: 9. GROUNDING CHECK — mechanical
    O->>O: check artifact freshness against codebase
    alt stale
        O->>B: "Update plan against current codebase."
        B-->>O: plan updated
        O->>A: "Re-review plan."
        A-->>O: reviewed
    end
    end

    O-->>H: PREPARED — ready for build
    O->>A: telec sessions end
    O->>B: telec sessions end
```

#### Step details

**1. Dispatch** — The orchestrator dispatches both workers with the same work
package. Each worker receives the todo's input (whatever it carries — brain
dump, existing requirements, any starting state). The workers are NOT linked
at this point.

**2. Independent intake** — Each worker reads and grounds itself independently:
the input, the codebase (ground truth), the roadmap (project direction), and
applicable domain docs. Each forms their own understanding before any
discussion. This independence is critical — it preserves the value of having
two perspectives. If they are linked during intake, one's confusion becomes
the other's confusion. The orchestrator knows intake is done when both workers
emit `agent_stop` (the standard notification for session idle).

**3. Link** — After both workers have stopped (intake complete), the
orchestrator links them via `telec sessions send <A> --direct`. From this
point, turn-complete outputs are cross-shared automatically.

**4. Discovery** — Pair-based. No roles. Both explore the problem through their
natural lens. They discuss, challenge each other, surface hidden assumptions,
check against codebase reality, resolve unknowns, and converge. When both
workers go idle, the orchestrator reads both tails and assesses: have they
converged? If yes, proceed to role assignment.

**5. Requirements** — Turn-based. The orchestrator messages only the writer
(`A`): "Write requirements based on your discussion." The reviewer (`B`) is
NOT messaged during the write phase — B passively observes A's work via the
direct link. When A goes idle (requirements written), the orchestrator messages
B: "Review — did the writer capture everything you discussed?" If B finds
gaps (`needs_work`), the orchestrator relays findings to A for fix-forward
correction, then B reviews again. No going back to discovery.

**6. Human interjection** — This is not a phase. The pair's direct link remains
open. The human reads the requirements and talks directly to the writer. Both
workers see the human's input via the direct link, so both can contribute. The
writer updates requirements per the human's feedback. The orchestrator tails
the conversation and proposes stamping approved when the human seems satisfied.
Fix-forward only — there is no rejection, only refinement.

**7. Test specs** — Turn-based. Same protocol: orchestrator messages only `A`
(writer). `B` observes silently via direct link. When A is done, orchestrator
messages B to review. Fix-forward loop if needed. Specs stay close to the
just-approved requirements while context is hot.

**8. Implementation plan** — Turn-based, roles flip. Orchestrator messages `B`
(writer — rigor lens drives execution planning). `A` observes silently via
direct link. When B is done, orchestrator messages A to review. Fix-forward
loop if needed.

**9. Grounding check** — Mechanical freshness check. If referenced files
changed since grounding, the plan writer (B) updates the plan, and the
reviewer (A) re-reviews.

**PREPARED** — Terminal success. Cleanup all sessions.

**BLOCKER** — The machine cannot proceed. Sessions stay alive for the human.

#### Turn-based protocol

During write/review turns, the orchestrator follows a strict protocol:

1. **Message only the writer.** The reviewer is not messaged during the write
   phase. The reviewer passively sees the writer's work via the direct link
   but produces no output.
2. **Wait for agent_stop.** The writer goes idle when done.
3. **Then message the reviewer.** "Review now." The reviewer produces output
   only when explicitly asked.
4. **Fix-forward on needs_work.** Relay findings to the writer. Writer fixes.
   Writer goes idle. Reviewer reviews again. No going back to discovery.
5. **Never message both simultaneously about the same task.** One works, the
   other waits. The direct link provides passive visibility without triggering
   responses.

### 3. Supervision

After dispatching workers:

1. Set a heartbeat timer.
2. Wait for worker notifications.
3. On notification: call `telec todo prepare [slug]` again to advance.
4. If a worker stalls (heartbeat fires with no progress), open a direct
   conversation to resolve. If still stuck after two iterations, record
   blockers and stop.

### Human touchpoints

- The human may edit preparation artifacts directly at any time, then hand the
  todo back to the machine with `telec todo reconcile [slug]`.
- The human approves requirements before test specs begin.
- The human may be escalated to when the machine or pair encounters a blocker
  requiring judgment.

### Events

| Phase transition            | Event                           |
| --------------------------- | ------------------------------- |
| Discovery dispatched        | `prepare.discovery_started`     |
| Requirements written        | `prepare.requirements_drafted`  |
| Requirements human-approved | `prepare.requirements_approved` |
| Test specs written          | `prepare.test_specs_drafted`    |
| Test specs reviewed         | `prepare.test_specs_approved`   |
| Plan written                | `prepare.plan_drafted`          |
| Plan reviewed               | `prepare.plan_approved`         |
| Grounding invalidated       | `prepare.grounding_invalidated` |
| Re-grounding completed      | `prepare.regrounded`            |
| Preparation complete        | `prepare.completed`             |
| Preparation blocked         | `prepare.blocked`               |

## Outputs

1. `requirements.md` — human-approved.
2. Test specification files (expected-failure-marked).
3. `implementation-plan.md`.
4. Grounding metadata in `todos.db` state.
5. Session cleanup on PREPARED terminal.

## Recovery

1. If a worker session fails, read the error and retry once. On second failure,
   record the blocker and stop.
2. If the state machine returns an unexpected instruction, log it and stop.
3. If direct conversation with a worker stalls, write blockers to `dor-report.md`
   and stop.
