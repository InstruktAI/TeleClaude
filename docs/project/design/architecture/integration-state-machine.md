---
description: 'Phase C state machine: lease-serialized, crash-recoverable integration from feature branches to canonical main.'
id: 'project/design/architecture/integration-state-machine'
domain: 'software-development'
scope: 'project'
type: 'design'
---

# Integration State Machine — Design

## Purpose

The Integration state machine is the **only role authorized to push canonical `main`**. It takes finalized feature branches from a durable FIFO queue, squash-merges them into an isolated integration worktree (`trees/_integration/`), pushes to origin, and cleans up. It is:

- **Serialized** by a lease (only one integrator at a time)
- **Crash-recoverable** via durable checkpoint
- **Queue-backed** (processes candidates in FIFO order by `ready_at`)
- **Self-ending** (exits when the queue is drained)

**Entry point:** `telec todo integrate [slug]`
**Implementation:** [`IntegrationPhase`](../../../../teleclaude/core/integration/state_machine.py) enum (12 states)
**Terminal state:** `COMPLETED`

### Referenced files

| File | Purpose |
|------|---------|
| [`teleclaude/core/integration/state_machine.py`](../../../../teleclaude/core/integration/state_machine.py) | State machine implementation (`IntegrationPhase` enum, `next_integrate()`) |
| [`teleclaude/core/integration/queue.py`](../../../../teleclaude/core/integration/queue.py) | Durable FIFO queue for integration candidates |
| [`teleclaude/core/integration/lease.py`](../../../../teleclaude/core/integration/lease.py) | Singleton lease for serialized integration |

### Referenced doc snippets

| Snippet ID | Content |
|------------|---------|
| `software-development/procedure/lifecycle/integration` | Integration procedure with agent actions |
| `project/spec/integration-orchestrator` | Full integrator contract (events, lease, queue, lifecycle) |
| `software-development/policy/version-control-safety` | Git safety rules for all agents |
| `software-development/policy/commits` | Commit format and attribution |

## Inputs/Outputs

**Inputs:**

- Integration FIFO queue — candidates `(slug, branch, sha, ready_at)` enqueued by Phase B handoff
- Integration lease — singleton lock ensuring only one integrator processes at a time
- Durable checkpoint at `{state_dir}/integrate-state.json` — enables crash recovery
- `origin/main` — canonical branch (fetched fresh before each merge)
- Feature branches on `origin/<slug>` — pushed by finalizer workers in Phase B

**Outputs:**

- Updated `origin/main` with squash-merged feature content (pushed from `trees/_integration/`)
- Delivery bookkeeping on repo root: `roadmap.yaml` → `delivered.yaml` transitions, demo promotion
- Cleanup: worktree removal, branch deletion, todo directory removal
- `integration.*` lifecycle events at each state transition
- Final status with metrics (`items_processed`, `items_blocked`, `duration_ms`)

### Checkpoint structure

The checkpoint enables crash recovery. Written atomically (temp file + `os.replace`) at every state transition:

```json
{
  "version": 1,
  "phase": "merge_clean",
  "candidate_slug": "my-feature",
  "candidate_branch": "my-feature",
  "candidate_sha": "abc123def...",
  "lease_token": "tok-xyz",
  "items_processed": 2,
  "items_blocked": 0,
  "started_at": "2026-03-08T10:00:00+00:00",
  "last_updated_at": "2026-03-08T10:05:00+00:00",
  "error_context": { "merge_type": "clean" },
  "pre_merge_head": "deadbeef..."
}
```

- `pre_merge_head` — SHA of main before merge, used to detect agent commits (HEAD advancement)
- `error_context` — phase-specific metadata (merge type, conflicted files, push rejection reason)

## Invariants

- **Singleton execution**: only one integrator session processes the queue at any time, enforced by an atomic lease with TTL=120s and 30s renewal.
- **FIFO ordering**: candidates processed in `ready_at` order. Deduplication by `(slug, branch, sha)`.
- **Isolation**: all merges happen in the persistent integration worktree `trees/_integration/`, reset to `origin/main` before each merge. Repo root cleanliness is irrelevant.
- **Crash safety**: every phase is recoverable. Re-calling `telec todo integrate` reads the durable checkpoint and resumes from the last persisted phase.
- **Already-integrated detection**: two guards prevent re-integrating content already on main (ancestry check + empty-merge guard).
- **Self-end authorization**: the integrator is the only governed session type allowed to self-end (when queue empty, no in-progress candidate, lease released, checkpoint written).
- **Workers cannot push main**: only the integrator pushes `origin/main`. Workers push only their feature branches.

## Primary flows

### State diagram

```mermaid
stateDiagram-v2
    [*] --> IDLE

    IDLE --> CANDIDATE_DEQUEUED: pop from queue
    IDLE --> COMPLETED: queue empty

    CANDIDATE_DEQUEUED --> MERGE_CLEAN: clean squash merge
    CANDIDATE_DEQUEUED --> MERGE_CONFLICTED: conflicted merge
    CANDIDATE_DEQUEUED --> CANDIDATE_DELIVERED: already integrated (skip)

    MERGE_CLEAN --> COMMITTED: HEAD advanced (commit detected)
    MERGE_CLEAN --> MERGE_CLEAN: no commit yet (re-prompt agent)

    MERGE_CONFLICTED --> COMMITTED: HEAD advanced (conflicts resolved + committed)
    MERGE_CONFLICTED --> MERGE_CONFLICTED: no commit yet (re-prompt agent)

    COMMITTED --> DELIVERY_BOOKKEEPING: bookkeeping complete

    DELIVERY_BOOKKEEPING --> PUSH_SUCCEEDED: git push OK
    DELIVERY_BOOKKEEPING --> PUSH_REJECTED: git push rejected

    PUSH_SUCCEEDED --> CLEANUP: proceed to cleanup

    PUSH_REJECTED --> PUSH_SUCCEEDED: agent recovered (heads match)
    PUSH_REJECTED --> PUSH_REJECTED: still diverged (re-prompt agent)

    CLEANUP --> CANDIDATE_DELIVERED: cleanup done

    CANDIDATE_DELIVERED --> IDLE: reset for next candidate

    COMPLETED --> [*]
```

### States reference

| State | Description | Agent Action Required | Auto-advance |
|-------|-------------|----------------------|--------------|
| `IDLE` | No candidate in progress. Pop next from queue or complete. | No | Yes |
| `CANDIDATE_DEQUEUED` | Candidate popped. Route to merge or skip. | No | Yes |
| `MERGE_CLEAN` | Squash merge succeeded. Staged changes await commit. | **Yes** — compose squash commit message | No |
| `MERGE_CONFLICTED` | Squash merge produced conflicts. | **Yes** — resolve conflicts + commit | No |
| `AWAITING_COMMIT` | Re-entry check: did the agent commit? | No | Yes |
| `COMMITTED` | Agent committed. Run delivery bookkeeping. | No | Yes |
| `DELIVERY_BOOKKEEPING` | Bookkeeping done. Push to origin. | No | Yes |
| `PUSH_SUCCEEDED` | Push landed. Proceed to cleanup. | No | Yes |
| `PUSH_REJECTED` | Push rejected (non-fast-forward). | **Yes** — rebase + push | No |
| `CLEANUP` | Remove worktree, branch, todo dir. | No | Yes |
| `CANDIDATE_DELIVERED` | Candidate fully integrated. Mark and reset. | No | Yes |
| `COMPLETED` | Queue empty. Terminal state. | **Yes** — self-end session | — |

### Single candidate flow

```mermaid
flowchart TD
    Pop["Pop candidate from queue\n(slug, branch, sha)"]

    AncestryCheck{"SHA already\nancestor of main?"}

    SetupWorktree["Reset integration worktree\nto origin/main"]

    SquashMerge["git merge --squash branch"]

    MergeResult{"Merge result?"}

    EmptyCheck{"Staged changes\n(git diff --cached)?"}

    CleanMerge["MERGE_CLEAN\nReturn: compose commit message"]
    ConflictMerge["MERGE_CONFLICTED\nReturn: resolve + commit"]

    CommitCheck{"HEAD advanced?\n(new commit detected)"}

    Bookkeeping["DELIVERY_BOOKKEEPING\n- roadmap deliver slug\n- demo create slug\n- commit bookkeeping"]

    Push["git push origin HEAD:main"]

    PushResult{"Push result?"}

    PushOK["PUSH_SUCCEEDED"]
    PushFail["PUSH_REJECTED\nReturn: rebase + retry"]

    RecoveryCheck{"Local HEAD ==\nremote main?"}

    DoCleanup["CLEANUP\n- Remove worktree\n- Delete branch\n- Remove todo dir"]

    Delivered["CANDIDATE_DELIVERED\n- Mark integrated in queue"]

    AlreadyMerged["Already integrated\n(skip candidate)"]
    EmptyMerge["Empty merge\n(content already on main)"]

    Pop --> AncestryCheck
    AncestryCheck -->|"Is ancestor"| AlreadyMerged
    AncestryCheck -->|"Not ancestor"| SetupWorktree

    SetupWorktree --> SquashMerge
    SquashMerge --> MergeResult

    MergeResult -->|"rc=0"| EmptyCheck
    MergeResult -->|"rc!=0"| ConflictMerge

    EmptyCheck -->|"No changes"| EmptyMerge
    EmptyCheck -->|"Has changes"| CleanMerge

    CleanMerge --> CommitCheck
    ConflictMerge --> CommitCheck

    CommitCheck -->|"Yes"| Bookkeeping
    CommitCheck -->|"No"| CleanMerge

    Bookkeeping --> Push
    Push --> PushResult

    PushResult -->|"rc=0"| PushOK
    PushResult -->|"rc!=0"| PushFail

    PushFail --> RecoveryCheck
    RecoveryCheck -->|"Yes"| PushOK
    RecoveryCheck -->|"No"| PushFail

    PushOK --> DoCleanup
    DoCleanup --> Delivered

    AlreadyMerged --> Delivered
    EmptyMerge --> Delivered
```

### Queue processing loop

```mermaid
flowchart TD
    Start(["telec todo integrate"])

    AcquireLease{"Acquire\nintegration lease?"}
    LeaseBusy(["LEASE_BUSY:\nanother integrator active"])

    CheckQueue{"Queue has\ncandidates?"}

    ProcessCandidate["Process next candidate\n(see single candidate flow)"]

    MarkIntegrated["Mark candidate\nas integrated"]

    MoreCandidates{"More candidates\nin queue?"}

    Complete(["COMPLETED:\nqueue drained\nrelease lease\nself-end session"])

    Start --> AcquireLease
    AcquireLease -->|"No"| LeaseBusy
    AcquireLease -->|"Yes"| CheckQueue

    CheckQueue -->|"No"| Complete
    CheckQueue -->|"Yes"| ProcessCandidate

    ProcessCandidate --> MarkIntegrated
    MarkIntegrated --> MoreCandidates

    MoreCandidates -->|"Yes"| ProcessCandidate
    MoreCandidates -->|"No"| Complete
```

### Clean merge (sequence diagram)

```mermaid
sequenceDiagram
    participant Agent as Integrator Agent
    participant SM as Integration Machine
    participant WT as trees/_integration/
    participant Origin as origin/main

    Agent->>SM: telec todo integrate
    SM->>SM: Acquire lease
    SM->>SM: Pop candidate (my-feature, sha=abc123)
    SM->>WT: git fetch origin, git reset --hard origin/main
    SM->>WT: git merge --squash origin/my-feature
    Note over WT: Merge succeeds (rc=0)
    SM->>WT: git diff --cached (non-empty)
    SM-->>Agent: MERGE_CLEAN: compose commit message

    Note over Agent: Agent reads diff stats,<br/>requirements.md, plan,<br/>composes commit message
    Agent->>WT: git commit -m "feat(my-feature): deliver ..."
    Agent->>SM: telec todo integrate

    SM->>SM: Detect HEAD advanced - COMMITTED
    SM->>SM: DELIVERY_BOOKKEEPING
    Note over SM: roadmap deliver my-feature<br/>demo create my-feature
    SM->>WT: git push origin HEAD:main
    Note over Origin: Push succeeds

    SM->>SM: CLEANUP
    Note over SM: Remove worktree branch<br/>Delete todo dir
    SM->>SM: Mark candidate integrated - IDLE
    SM->>SM: Check queue - empty - COMPLETED
    SM-->>Agent: COMPLETED - self-end
    Agent->>Agent: telec sessions end self
```

### Conflict resolution (sequence diagram)

```mermaid
sequenceDiagram
    participant Agent as Integrator Agent
    participant SM as Integration Machine
    participant WT as trees/_integration/

    Agent->>SM: telec todo integrate
    SM->>WT: git merge --squash origin/my-feature
    Note over WT: Merge conflicts (rc!=0)
    SM->>SM: Detect conflicted files
    SM-->>Agent: MERGE_CONFLICTED:<br/>conflicted files: [src/foo.py, src/bar.py]

    Note over Agent: Agent reads each conflicted file,<br/>understands both sides,<br/>resolves conflict markers
    Agent->>WT: Edit conflicted files
    Agent->>WT: git add src/foo.py src/bar.py
    Agent->>WT: git commit -m "feat(my-feature): deliver ..."
    Agent->>SM: telec todo integrate

    SM->>SM: Detect HEAD advanced - COMMITTED
    Note over SM: Continue with bookkeeping - push - cleanup
```

### Push rejection recovery (sequence diagram)

```mermaid
sequenceDiagram
    participant Agent as Integrator Agent
    participant SM as Integration Machine
    participant WT as trees/_integration/
    participant Origin as origin/main

    SM->>WT: git push origin HEAD:main
    Origin-->>SM: rejected (non-fast-forward)
    SM-->>Agent: PUSH_REJECTED:<br/>reason: "non-fast-forward update"

    Note over Agent: Another push landed while<br/>integrator was processing
    Agent->>WT: git fetch origin
    Agent->>WT: git rebase origin/main
    Note over Agent: Resolve rebase conflicts if any
    Agent->>WT: git push origin HEAD:main
    Agent->>SM: telec todo integrate

    SM->>SM: Check: local HEAD == remote main?
    Note over SM: Yes - PUSH_SUCCEEDED
    SM->>SM: Continue with CLEANUP
```

### Architecture overview

```mermaid
flowchart TB
    subgraph "Event Sources"
        ReviewApproved["review_approved event"]
        FinalizeReady["finalize_ready event"]
        BranchPushed["branch_pushed event"]
    end

    subgraph "Readiness Projection"
        Predicate["Readiness Predicate:\n1. review_approved exists\n2. finalize_ready exists\n3. branch_pushed exists\n4. SHA reachable on remote\n5. Not superseded\n6. Not already on main"]
    end

    subgraph "Serialization Layer"
        Queue["Integration Queue\n(FIFO, durable)"]
        Lease["Integration Lease\n(singleton, TTL=120s)"]
    end

    subgraph "Integration Worktree"
        IWT["trees/_integration/\n(persistent, reset to origin/main)"]
    end

    subgraph "State Machine"
        SM["IntegrationPhase\n12 states, checkpoint-backed"]
    end

    subgraph "Outputs"
        Main["origin/main\n(canonical)"]
        Cleanup2["Cleanup\n(worktree + branch + todo)"]
        Events["Lifecycle Events\n(fire-and-forget)"]
    end

    ReviewApproved --> Predicate
    FinalizeReady --> Predicate
    BranchPushed --> Predicate

    Predicate -->|"ALL conditions met"| Queue
    Queue --> Lease
    Lease -->|"acquired"| SM
    SM --> IWT
    IWT --> Main
    SM --> Cleanup2
    SM --> Events
```

### Lease and queue mechanics

The integration lease enforces singleton execution — only one integrator session processes the queue at any time:

```mermaid
flowchart LR
    subgraph "Lease Lifecycle"
        Acquire["Acquire\n(compare-and-swap)"]
        Hold["Hold\n(renew every 30s)"]
        Release["Release\n(queue drained)"]
        Expire["Expire\n(TTL=120s)"]
        Break["Break\n(new session acquires\nafter expiry)"]
    end

    Acquire --> Hold
    Hold --> Release
    Hold --> Expire
    Expire --> Break
    Break --> Acquire
```

| Property | Value |
|----------|-------|
| Lease key | `integration/main` |
| TTL | 120 seconds |
| Renew interval | 30 seconds |
| Acquisition | Atomic compare-and-swap |
| Stale break | Allowed after expiry |
| Queue order | FIFO by `ready_at` timestamp |
| Queue deduplication | By `(slug, branch, sha)` |
| Queue item states | `queued` → `in_progress` → `integrated` / `blocked` / `superseded` |

### Already-integrated detection

Two guards prevent re-integrating content already on main:

```mermaid
flowchart TD
    Candidate["Candidate\n(slug, branch, sha)"]

    Guard1{"Guard 1: Ancestry\ngit merge-base\n--is-ancestor sha HEAD"}
    Guard2{"Guard 2: Empty merge\ngit diff --cached --quiet\n(after squash merge)"}

    Skip["CANDIDATE_DELIVERED\n(skip - already integrated)"]
    Proceed["Continue with merge"]

    Candidate --> Guard1
    Guard1 -->|"Is ancestor"| Skip
    Guard1 -->|"Not ancestor"| Guard2
    Guard2 -->|"No staged changes"| Skip
    Guard2 -->|"Has changes"| Proceed
```

- **Guard 1 (ancestry):** fast path for regular merges where git maintains ancestry links.
- **Guard 2 (empty merge):** catches squash merges — squash commits don't create ancestry links, so Guard 1 misses them. After `git merge --squash`, if `git diff --cached` shows no changes, the content is already on main.

Both guards emit `integration.candidate.already_merged` lifecycle events.

### Delivery bookkeeping

After the agent commits the squash merge, the machine runs bookkeeping on the **repo root** (not the integration worktree):

```mermaid
flowchart TD
    Committed["COMMITTED"]

    IsBug{"Is bug slug?"}

    Deliver["telec roadmap deliver slug\n(roadmap.yaml - delivered.yaml)"]
    DemoCreate["telec todo demo create slug\n(if demo.md exists)"]

    Stage["git add\ntodos/roadmap.yaml\ntodos/delivered.yaml"]
    Commit["git commit\n'chore: deliver slug'"]

    Push["DELIVERY_BOOKKEEPING\ncomplete"]

    Committed --> IsBug
    IsBug -->|"No"| Deliver
    IsBug -->|"Yes"| Stage
    Deliver --> DemoCreate
    DemoCreate --> Stage
    Stage --> Commit
    Commit --> Push
```

Only bookkeeping files are staged (`git add` by path, not `git add -A`), preserving any dirty state on main.

### Crash recovery

Every phase is recoverable. Re-calling `telec todo integrate` reads the checkpoint and resumes:

```mermaid
flowchart LR
    subgraph "Crash Points"
        C1["After dequeue,\nbefore merge"]
        C2["After merge,\nbefore commit"]
        C3["After commit,\nbefore push"]
        C4["After push\nrejection"]
        C5["During cleanup"]
        C6["After candidate\ndelivered"]
    end

    subgraph "Recovery Behavior"
        R1["Resume at merge.\nNo work lost."]
        R2["Re-prompt for commit.\nGit index persists."]
        R3["Re-run bookkeeping\n(idempotent). Push."]
        R4["Re-check if heads match.\nRe-prompt if not."]
        R5["Re-run cleanup\n(idempotent)."]
        R6["Mark integrated.\nReset to IDLE."]
    end

    C1 --> R1
    C2 --> R2
    C3 --> R3
    C4 --> R4
    C5 --> R5
    C6 --> R6
```

| Crash Point | Checkpoint Phase | Recovery |
|-------------|-----------------|----------|
| After dequeue, before merge | `CANDIDATE_DEQUEUED` | Routes to merge. No work lost. |
| After merge, before commit | `MERGE_CLEAN` / `MERGE_CONFLICTED` | Re-prompts agent. Staged changes persist in git index. |
| After commit, before push | `COMMITTED` | Re-runs delivery bookkeeping (idempotent). Then pushes. |
| After push rejection | `PUSH_REJECTED` | Re-checks if heads match. Re-prompts if not. |
| During cleanup | `CLEANUP` | Re-runs cleanup (idempotent). Missing worktrees are no-ops. |
| After candidate delivered | `CANDIDATE_DELIVERED` | Marks integrated, resets to IDLE, loops for next. |

### Lifecycle events

| Event | Emitted When |
|-------|-------------|
| `integration.started` | First candidate dequeued in a session |
| `integration.candidate.dequeued` | Candidate popped from queue |
| `integration.candidate.already_merged` | Candidate skipped (ancestry or empty merge) |
| `integration.merge.succeeded` | Clean squash merge completed |
| `integration.merge.conflicted` | Squash merge produced conflicts |
| `integration.candidate.committed` | Agent commit detected (HEAD advanced) |
| `integration.push.succeeded` | Push to origin succeeded |
| `integration.push.rejected` | Push to origin rejected |
| `integration.candidate.delivered` | Candidate fully integrated and cleaned up |
| `integration.candidate.blocked` | Candidate blocked (via queue mark) |

### Internal loop

`_dispatch_sync` runs a capped loop (50 iterations) that reads the checkpoint, dispatches to the appropriate phase handler, and either loops internally (for autonomous transitions like COMMITTED → BOOKKEEPING → PUSH → CLEANUP) or returns an instruction string (for agent decision points like MERGE_CLEAN, MERGE_CONFLICTED, PUSH_REJECTED). This enables multi-phase advancement in a single `telec todo integrate` call.

## Failure modes

- **Lease already held**: returns `LEASE_BUSY` — exit immediately. Do not attempt to break the lease.
- **Queue empty**: returns `COMPLETED` — self-end the session.
- **Merge conflicts (unresolvable)**: agent leaves uncommitted, machine re-prompts. If genuinely unresolvable, call `telec todo integrate` without committing — the machine detects no HEAD advancement and re-prompts.
- **Push repeatedly rejected**: agent fetches, rebases, resolves rebase conflicts, pushes in integration worktree. If the problem persists, check for concurrent integrators (should not happen with lease, but may indicate stale lease).
- **Candidate already integrated**: silent skip to CANDIDATE_DELIVERED. No agent action needed. Emits `integration.candidate.already_merged`.
- **Checkpoint corrupt or missing**: resets to IDLE, starts fresh. No manual editing needed.
- **Integration worktree missing**: created on first use, reused after. Missing worktree is auto-created.
- **Auto-enqueue fallback**: when called with explicit slug not in queue, auto-enqueues from local branch (branch name == slug convention), provided SHA is not already ancestor of main.
