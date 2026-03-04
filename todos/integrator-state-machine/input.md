# Input: integrator-state-machine

## Origin

Delivered `integrator-wiring` wired the integration module into production but left
the `/next-integrate` command as prose instructions for the agent to interpret.
The integration module has all the primitives (lease, queue, readiness projection,
clearance probe, runtime) but no deterministic entry-point script that advances
state and returns control to the agent at decision points.

## Problem

The integrator agent currently receives prose instructions and must figure out
how to call `IntegratorShadowRuntime`, manage the queue, do git operations, write
commits, handle conflicts, do delivery bookkeeping, and clean up — all from
reading a markdown command spec. This is fragile: the agent may skip steps,
misorder operations, or fail to use the existing primitives correctly.

## Desired outcome

An idempotent state machine (like `telec todo work` for the orchestrator) that the
integrator agent calls repeatedly. Each call:

1. Reads current state from a durable checkpoint
2. Executes the next deterministic block (git operations, queue management, delivery
   bookkeeping, cleanup)
3. Stops at a decision point and returns structured instructions to the agent
4. The agent acts on the decision (commit message, conflict resolution, push recovery)
5. The agent calls the state machine again
6. The state machine validates the decision was executed, advances state, continues

The state machine is the authority on sequencing. The agent is the authority on
intelligence. Neither does the other's job.

## Actor model

Per candidate in the queue:

1. **Script turn:** Acquire lease → pop candidate → wait for main clearance →
   fetch + pull main → squash merge branch → STOP.
   Returns: success (staged changes, branch commits, requirements, plan, diff stats)
   or conflict (conflict file list, partial merge state).

2. **Agent turn:** If conflict — resolve, stage. Then compose squash commit message
   from requirements + implementation plan + branch commit history. `git commit`.

3. **Script turn:** Delivery bookkeeping (roadmap deliver, demo snapshot if exists,
   stage, commit) → push main → STOP.
   Returns: success or push-rejected (rejection reason).

4. **Agent turn (only if push rejected):** Pull, rebase/resolve, retry push.

5. **Script turn:** Emit deployment.completed → cleanup (worktree, branch, todo dir,
   commit cleanup) → restart daemon → mark integrated → write checkpoint → pop next
   candidate → loop to 1 or exit if queue empty.

6. **Agent turn:** Self-end when script exits with empty queue.

## Decision points (where agent intelligence is required)

- **Squash commit message:** The agent reads `requirements.md` (goal + scope),
  `implementation-plan.md` (task structure), all branch commit messages
  (`git log main..{branch}`), and diff stats. It composes a commit message that
  captures the delivery's full intent, scope, and structure.

- **Conflict resolution:** The agent reads conflicted files, understands the code
  context, resolves conflicts, and stages the resolution.

- **Push rejection recovery:** The agent diagnoses the rejection, pulls latest main,
  rebases or re-merges, resolves any new conflicts, and retries the push.

## Idempotency contract

- The state machine reads its checkpoint before every invocation
- If called again at the same state, it produces the same output
- If the agent crashes mid-turn, the next invocation resumes from the last checkpoint
- The lease prevents concurrent integrators
- Queue transitions are durable (file-backed with fsync)

## Existing primitives to wire (all delivered, tested)

- `IntegratorShadowRuntime` — lease, queue drain, clearance probe, checkpoint
- `IntegrationQueue` — durable FIFO with status transitions
- `IntegrationLeaseStore` — singleton lease with TTL and renewal
- `ReadinessProjection` — candidate readiness lookup
- `MainBranchClearanceProbe` — checks no other session is modifying main
- `BlockedFollowUpStore` — links blocked candidates to follow-up todos
- `integration_bridge.py` — event emission helpers (deployment.completed, deployment.failed)
- `IntegratorCutoverControls` — authorization gate

## CLI entry point

`telec todo integrate <slug>` — the public interface for both agents and admins.

- Mirrors `telec todo work <slug>`: call it, get a structured instruction block back,
  act on it, call again.
- The `/next-integrate` agent command calls it repeatedly in a loop.
- Admins can call it manually to trigger integration for a specific slug, or to
  inspect what state a candidate is in and what would happen next.
- The trigger cartridge's `spawn_integrator_session` spawns an agent that calls this
  command — it's the automatic path. `telec todo integrate` is the manual path to the
  same state machine.

## Integrator lifecycle events

Every state transition emits an event through the pipeline. The events serve
three purposes: observability (dashboard/timeline), audit trail (what happened
and when), and checkpoint alignment (the last emitted event matches the
checkpoint state — if the integrator crashes, it resumes from the last event).

All events carry the integrator `session_id` as source, enabling full
reconstruction of one integration run by filtering `integration.*`.

| Event | When | Key payload |
|---|---|---|
| `integration.started` | Lease acquired, integrator alive | triggering slug, session_id, queue depth |
| `integration.candidate.dequeued` | Popped candidate, starting work | slug, branch, sha, queue position |
| `integration.merge.succeeded` | Squash merge clean, staged | slug, branch, files changed, insertions, deletions |
| `integration.merge.conflicted` | Squash merge hit conflicts | slug, branch, conflicted file list |
| `integration.conflict.resolved` | Agent resolved conflicts | slug, branch, resolution file count |
| `integration.candidate.committed` | Agent wrote squash commit | slug, commit sha, commit message subject |
| `integration.push.succeeded` | Main pushed to origin | slug, commit sha |
| `integration.push.rejected` | Push failed, agent recovering | slug, rejection reason |
| `integration.candidate.delivered` | Candidate fully done — pushed, bookkeeping, cleanup | slug, branch, merge commit sha, duration |
| `integration.candidate.blocked` | Candidate unrecoverable, follow-up created | slug, branch, block reason, follow-up slug |
| `integration.completed` | Queue empty, lease released, self-ending | candidates processed, candidates blocked, total duration |

These flow through the same pipeline as all other events. The notification
projector can create alerts for `integration.merge.conflicted` and
`integration.candidate.blocked`. A dashboard queries the event stream filtered
by `integration.*` for the full timeline.

## Prior art

- `teleclaude/core/next_machine/core.py` — the work state machine (`telec todo work`)
  is the template: deterministic Python that returns structured instruction blocks,
  called repeatedly by the orchestrator agent.
