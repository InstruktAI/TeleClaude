---
id: 'project/spec/feature/workflow/integration-state-machine'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Singleton, lease-serialized, durable-checkpoint state machine that squash-merges finalize-ready todos into origin/main from an isolated integration worktree.'
---

# Integration State Machine — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

The integration state machine is Phase C of the todo lifecycle — the only authorized writer of canonical `origin/main`. It runs as a singleton (one active integrator per project, enforced by a file-backed lease keyed on `integration/main`) and consumes finalize-ready Todos in FIFO order. Each call resumes from a durable checkpoint, executes the next deterministic step, and either loops internally or returns a structured instruction block that asks the calling agent to do the one thing only intelligence can do: compose a squash commit message, resolve a merge conflict, or recover from a rejected push. All git mutations happen inside an isolated integration worktree at `trees/_integration/`, never on repo root, so a dirty or diverged repo root never blocks delivery. When the queue drains, the integrator emits `workflow.todo.delivered` per slug, removes per-slug worktrees and branches, archives binary artifacts, and ends.

## Canonical fields

### Use cases

```
Given the integrator is idle with no active candidate
And one or more worktrees report finalize.status of "ready"
When `telec todo integrate` is invoked
Then the integrator sweeps already-delivered worktrees, acquires the singleton lease,
And dequeues the FIFO-earliest candidate by (ready_at, slug)
And ensures the persistent integration worktree at `trees/_integration/` is synced to origin/main
And performs `git merge --squash` of the candidate branch
And emits `integration.started`, `integration.candidate.dequeued`, and `integration.merge.succeeded`
```

```
Given the squash merge applied cleanly in the integration worktree
When the state machine writes phase MERGE_CLEAN to its checkpoint
Then it returns an AWAITING_COMMIT instruction containing diff stats, branch log, requirements and implementation plan
And the calling agent composes the squash commit message and runs `git commit` inside `trees/_integration/`
And the next `telec todo integrate` call detects HEAD advanced past pre_merge_head
And the checkpoint advances to COMMITTED, then DELIVERY_BOOKKEEPING in the same loop iteration
```

```
Given the squash merge produced conflicts
When the state machine writes MERGE_CONFLICTED with the list of conflicted files
Then it returns a structured conflict-resolution instruction listing those files
And the calling agent resolves the conflicts and commits inside the integration worktree
And the next call observes MERGE_HEAD cleared and HEAD advanced and advances to COMMITTED
And emits `integration.merge.conflicted` at the original conflict and `integration.candidate.committed` on resolution
```

```
Given the candidate SHA is already an ancestor of HEAD on origin/main (stale re-queue after restart)
Or the squash merge produced an empty staged diff (squash of already-integrated commits)
When `_do_merge` runs
Then the candidate skips merge and commit entirely
And the checkpoint advances to CANDIDATE_DELIVERED
And `integration.candidate.already_merged` is emitted
And any leftover SQUASH_MSG file is removed
```

```
Given the bookkeeping commit and squash commit are staged in the integration worktree
When `git push origin HEAD:main` is rejected (remote moved)
Then the state machine writes PUSH_REJECTED with the rejection reason
And returns an instruction asking the agent to rebase onto origin/main and push from the integration worktree
And the next call computes local HEAD vs remote main; if they match, recovery is detected and phase advances to PUSH_SUCCEEDED
And `integration.push.rejected` is emitted at rejection and `integration.push.succeeded` on recovery
```

```
Given another integrator session holds the `integration/main` lease and the TTL has not elapsed
When `telec todo integrate` is invoked
Then `_step_idle` reports lease busy with the holder session id and returns immediately without touching git
And no integration lifecycle events are emitted for this call
```

```
Given the integrator was killed mid-flight at any phase
When a fresh `telec todo integrate` is invoked
Then the durable checkpoint at the integration state dir is read on entry
And `_dispatch_sync` resumes from the same phase the prior run was in
And idempotency guards (ancestry check, empty-squash check, head-advanced check, HEAD-vs-remote check) prevent double-merge or double-commit
```

```
Given repo root main is dirty when `_dispatch_sync` runs `git pull --ff-only --autostash origin main`
And the autostash pop fails after the pull, leaving an orphaned stash entry
When the integrator detects the stash count increased between entry and post-pull
Then it returns a formatted `repo_root_diverged` or `autostash_orphaned` instruction
And no candidate is dequeued for this call
```

### Implementation pointers (v1)

- `teleclaude/core/integration/state_machine.py:68-155` — `_dispatch_sync` outer loop, repo-root autostash recovery, fresh-IDLE counter reset, 50-iteration cap
- `teleclaude/core/integration/state_machine.py:158-264` — `_step` phase dispatcher covering all 12 `IntegrationPhase` values
- `teleclaude/core/integration/state_machine.py:272-305` — `next_integrate` async entry, thread-offloaded sync loop
- `teleclaude/core/integration/checkpoint.py:30-44` — `IntegrationPhase` enum (12 states)
- `teleclaude/core/integration/checkpoint.py:47-65` — `IntegrationCheckpoint` durable record with `pre_merge_head`, `warnings`, `error_context`
- `teleclaude/core/integration/checkpoint.py:136-161` — atomic checkpoint write via temp-file + `os.replace` + `fsync`
- `teleclaude/core/integration/lease.py:68-192` — `IntegrationLeaseStore` with file lock, 120s default TTL, atomic acquire/renew/release
- `teleclaude/core/integration/step_functions.py:41-43` — lease key `integration/main`, TTL 120s
- `teleclaude/core/integration/step_functions.py:141-177` — `_ensure_integration_worktree` (creates `trees/_integration/` detached at origin/main, preserves in-progress merge/squash state)
- `teleclaude/core/integration/step_functions.py:246-344` — `_scan_finalize_ready_candidates` / `_verify_slug_ready` accept `finalize.status == "ready"` after read-time upcycle normalization
- `teleclaude/core/integration/step_functions.py:413-474` — `_step_idle` (sweep delivered, scan or verify slug, acquire lease, dequeue, emit `integration.started`)
- `teleclaude/core/integration/step_functions.py:477-570` — `_do_merge` with two already-merged guards (ancestor merge-base and empty-cached-diff for squash)
- `teleclaude/core/integration/step_functions.py:636-726` — `_step_delivery_bookkeeping` (`deliver_sync`, dependency reference cleanup, cleanup commit, `push origin HEAD:main` under `main_branch_lock`)
- `teleclaude/core/integration/step_functions.py:760-806` — `_step_push_succeeded` syncs repo root, pushes repo-root bookkeeping if ahead, then runs cleanup
- `teleclaude/core/integration/step_functions.py:823-865` — `_do_cleanup` delegates to `cleanup_delivered_slug`, increments `items_processed`, advances to CANDIDATE_DELIVERED
- `teleclaude/api/todo_routes.py:187-208` — `POST /todos/integrate` submits durable receipt-backed operation via `operations.submit_todo_integrate`
- `teleclaude/cli/tool_commands/todo.py:185-220` — `telec todo integrate [<slug>]` CLI handler

### Cross-context references

- `agent_runtime` — receives fire-and-forget lifecycle events emitted via `integration_bridge`: `integration.started`, `integration.candidate.dequeued`, `integration.candidate.already_merged`, `integration.merge.succeeded`, `integration.merge.conflicted`, `integration.candidate.committed`, `integration.push.succeeded`, `integration.push.rejected`, `integration.candidate.delivered`, `integration.candidate.blocked`
- `workflow` — `deliver_sync` records the delivery commit in `todos.db` during DELIVERY_BOOKKEEPING; `workflow.todo.delivered` event is emitted by the workflow context after push succeeds
- `operations` — `POST /todos/integrate` returns a `SerializedOperation` receipt; the integrator runs inside the operation runner so failures surface through operation status

## Known caveats

- The integrator is the only writer authorized to push `origin/main`. Worker sessions on per-slug branches push their feature branches only; main is reachable solely through this state machine.
- Two already-merged guards exist because `git merge --squash` does **not** create ancestry edges between the source branch and the merge commit. The ancestry check (`merge-base --is-ancestor`) catches non-squash re-queues; the empty-staged-diff check catches squash re-queues. Both are required.
- Delivery bookkeeping commits (roadmap delivery, dependency-reference cleanup, cleanup commit) are created inside `trees/_integration/`, not on repo root. Only the bookkeeping changes plus the squash are pushed; `git add -A` is never used.
- After a successful push, the integrator best-effort `git pull --ff-only` on repo root and pushes any repo-root bookkeeping that is ahead. Pull failure is non-fatal — cleanup proceeds regardless, and a warning surfaces in the COMPLETED summary.
- When `_step_idle` is called with an explicit slug, only that slug is verified against `state.finalize.status == "ready"`; the FIFO scan is bypassed but ancestry and remote-branch existence checks still apply.
- The normal enqueue path is event-triggered: `domain.software-development.planning.todo_finalize_ready` wakes the integration trigger cartridge, which spawns the singleton integrator. The scanner remains the recovery path for missed events.
- Legacy rows are normalized before scanner pickup, so older persisted `finalize.status="handed_off"` rows read back as `finalize.status="ready"` and are picked up by the same rule.
- The 50-iteration `_LOOP_LIMIT` exists so multi-phase advances (e.g., COMMITTED → DELIVERY_BOOKKEEPING → PUSH_SUCCEEDED → CLEANUP → CANDIDATE_DELIVERED → IDLE → next candidate) can complete in one call without forcing the agent back through `telec todo integrate` repeatedly.
- The phase enum's `AWAITING_COMMIT` value is reachable but typically not written; `MERGE_CLEAN` and `MERGE_CONFLICTED` are written directly and re-entry handling treats all three equivalently via `_step_awaiting_commit`.
- Lifecycle event emission is fire-and-forget via `asyncio.run_coroutine_threadsafe`; event delivery failure never blocks integration progress and is only logged at debug level.
- Post-delivery hook: if `tools/post_pull_check.py` exists in the project, the state machine pauses after each `CANDIDATE_DELIVERED` and returns a formatted post-delivery-check instruction; without that script it loops straight to IDLE.
