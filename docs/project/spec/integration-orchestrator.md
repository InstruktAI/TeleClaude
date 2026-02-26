---
id: 'project/spec/integration-orchestrator'
type: 'spec'
scope: 'project'
description: 'Event-driven singleton integrator contract for serial branch-to-main delivery.'
---

# Integration Orchestrator — Spec

## Definition

The Integration Orchestrator is the only role authorized to merge and push canonical `main`.
It is event-driven, queue-backed, and serialized by a lease so parallel workers can deliver safely
without race conditions on `main`.

This spec defines:

- canonical integration events and payload requirements,
- readiness conditions for integration candidates,
- singleton lease semantics,
- integrator lifecycle and shutdown behavior,
- self-end authorization boundaries for session types.

## Machine-Readable Surface

```yaml
integrator:
  authority:
    only_role_that_can_push_main: true
    workers_can_push_feature_branches: true

  trigger_events:
    - review_approved
    - finalize_ready
    - branch_pushed

  non_trigger_signals:
    - worktree_dirty_to_clean
    - heartbeat_only

  required_event_fields:
    review_approved:
      - slug
      - approved_at
      - review_round
      - reviewer_session_id
    finalize_ready:
      - slug
      - branch
      - sha
      - worker_session_id
      - orchestrator_session_id
      - ready_at
    branch_pushed:
      - branch
      - sha
      - remote
      - pushed_at
      - pusher

  readiness_predicate:
    all_required_events_present: true
    branch_matches_finalize_ready: true
    sha_matches_finalize_ready: true
    sha_reachable_on_remote_branch: true
    slug_not_superseded_by_newer_finalize_ready: true
    sha_not_already_integrated_to_main: true

  serialization:
    lease_key: integration/main
    single_active_holder: true
    queue_is_durable: true
    queue_order: fifo_by_ready_at

  lease_defaults:
    ttl_seconds: 120
    renew_every_seconds: 30
    stale_break_policy: allowed_when_expired

  integrator_exit:
    allowed_when:
      - queue_empty
      - no_item_in_progress
      - lease_released
      - checkpoint_written
```

## Canonical Events

### `review_approved`

Meaning: slug has passed review gates and is eligible for finalize-prepare.

Required fields:

- `slug`
- `approved_at` (ISO8601)
- `review_round` (int)
- `reviewer_session_id`

### `finalize_ready`

Meaning: finalize-prepare completed in worktree and declared merge readiness.

Required fields:

- `slug`
- `branch`
- `sha` (branch HEAD used for integration)
- `worker_session_id`
- `orchestrator_session_id` (session that consumed worker output and recorded readiness)
- `ready_at` (ISO8601)

### `branch_pushed`

Meaning: the candidate commit is published to remote and can be integrated from canonical refs.

Required fields:

- `branch`
- `sha`
- `remote` (normally `origin`)
- `pushed_at` (ISO8601)
- `pusher` (identity label)

## Readiness Predicate

An integration candidate `(slug, branch, sha)` is `READY` only when:

1. A `review_approved` exists for `slug`.
2. A `finalize_ready` exists for `(slug, branch, sha)`.
3. A `branch_pushed` exists for `(branch, sha)` on the configured remote.
4. `sha` is reachable from `origin/<branch>`.
5. No newer `finalize_ready` for the same `slug` supersedes this `(branch, sha)`.
6. `sha` is not already reachable from `origin/main`.

`worktree dirty -> clean` is explicitly not a readiness signal.

## Lease and Queue Semantics

### Lease

The integrator lease enforces singleton execution:

- Lease key: `integration/main`
- Required fields:
  - `owner_session_id`
  - `lease_token`
  - `acquired_at`
  - `renewed_at`
  - `expires_at`
- Acquisition must be atomic (compare-and-swap or equivalent).
- Renew every `renew_every_seconds`.
- If expired, a new session may acquire and continue queue processing.

### Queue

Queue is durable and event-derived:

- Items are candidates `(slug, branch, sha, ready_at)`.
- Enqueue only when predicate transitions from `NOT_READY` to `READY`.
- Deduplicate by `(slug, branch, sha)`.
- Process in FIFO order by `ready_at`.
- Keep status per item: `queued | in_progress | integrated | blocked | superseded`.

## Integrator Lifecycle

1. Event ingestion updates projection state for candidate readiness.
2. If any candidate becomes `READY`, attempt lease acquisition.
3. If lease is acquired:
   - start integrator session (or continue existing holder),
   - drain queue serially.
4. For each candidate:
   - re-check readiness predicate just before apply,
   - integrate from clean canonical refs,
   - emit `integration_completed` or `integration_blocked`.
5. When queue empty:
   - wait short grace window for late events,
   - if still empty, release lease and self-end.

Multiple trigger events may arrive concurrently; only one active lease holder processes them.
Other events are queued and consumed by that same active integrator.

## Integration Workflow Contract

For each queued candidate:

1. Prepare clean integration workspace from latest `origin/main`.
2. Merge `origin/<branch>` (or specific `sha`) into integration workspace.
3. If merge conflict:
   - emit `integration_blocked` with conflict files and slug/branch/sha,
   - mark queue item `blocked`,
   - do not push partial merge.
4. If merge succeeds:
   - push canonical `main`,
   - run delivery bookkeeping for non-bug slugs,
   - run demo snapshot/cleanup lifecycle,
   - emit `integration_completed`.

## Self-End Authorization Matrix

| Session type                    | Self-end allowed | Conditions                                                                 |
| ------------------------------- | ---------------- | -------------------------------------------------------------------------- |
| Builder / Reviewer / Fix worker | No               | Orchestrator owns completion and evidence consumption.                     |
| Finalizer (prepare stage)       | No               | Must emit `FINALIZE_READY`; orchestrator consumes evidence.                |
| Orchestrator (general)          | No               | Must remain resumable and externally controlled.                           |
| Integrator                      | Yes              | Queue empty, no in-progress candidate, lease released, checkpoint emitted. |
| Non-governed utility session    | Yes              | No pending governed handoff obligations.                                   |

## Constraints

- Only integrator may push canonical `main`.
- Workers may push only their feature/worktree branches.
- Integration is serialized by lease + durable queue, not by heartbeat timing.
- Dirty canonical `main` must never be used as integration source-of-truth.
