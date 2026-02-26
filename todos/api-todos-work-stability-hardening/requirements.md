# Requirements: api-todos-work-stability-hardening

## Problem

`/todos/work` currently executes expensive preparation and sync steps on every
call, even when the slug worktree is already prepared and unchanged. That makes
request latency unpredictable and correlates with watchdog loop-lag alerts.

## Intended Outcome

Keep the current safety/correctness behavior of `next_work(...)`, but make
repeated calls for unchanged slugs fast, deterministic, and diagnosable.

## Scope

### In scope

1. **R1 - Phase observability**
   Add structured per-phase timing logs for the `/todos/work` request path so
   operators can see exactly where time is spent.
2. **R2 - Conditional preparation**
   Replace unconditional "always prepare existing worktree" behavior with a
   deterministic decision policy that prepares only when needed.
3. **R3 - Per-slug single-flight**
   Ensure concurrent calls for the same slug do not duplicate expensive prep
   subprocesses.
4. **R4 - Conditional sync**
   Avoid redundant main-to-worktree and slug-artifact sync work when source
   inputs are unchanged.
5. **R5 - Behavior parity and safety**
   Preserve existing dependency checks, phase transitions, build gates, and
   error contracts (including prep-failure reporting).
6. **R6 - Verification coverage**
   Add/update tests for prep decision logic, concurrency behavior, and sync
   skip/execute conditions.

### Out of scope

- Database-layer changes (`aiosqlite` replacement, backend migration).
- Host/service-manager changes (`launchctl`, `systemctl`, daemon unit wiring).
- Broad `next_machine` redesign unrelated to `/todos/work` latency.
- Watchdog-threshold tuning without phase-level evidence.

## Success Criteria

1. Repeated `/todos/work` calls for an unchanged, prepared slug do not execute
   `_prepare_worktree(...)` each time.
2. Logs expose per-phase duration and decision context (slug + phase +
   decision/reason) for `/todos/work`.
3. Concurrent same-slug calls trigger at most one prep execution for that slug.
4. Existing orchestration behavior remains intact (no regressions in build/review
   flow, dependency gating, or finalize readiness paths).
5. Tests explicitly cover:
   - prep skipped when unchanged,
   - prep executed when required signals are present,
   - single-flight behavior under concurrent same-slug requests,
   - sync skipped only when safe.

## Verification Path

- Unit tests for prep policy and sync policy in `next_machine` helpers.
- Unit tests for `next_work(...)` concurrent-call behavior and safety invariants.
- Observable daemon logs confirming phase timings and prep/sync decisions.

## Dependencies and Preconditions

- This todo has no `after` dependency in `todos/roadmap.yaml`.
- Worktree creation/preparation commands must remain available in the runtime
  environment.
- Log access via `instrukt-ai-logs teleclaude --since <window> --grep <pattern>`
  must be functional for operational verification.

## Integration Safety

- Changes remain localized to `next_machine` worktree orchestration and tests.
- Rollback path is straightforward: restore unconditional prep/sync behavior in
  `next_work(...)`/`ensure_worktree(...)` if regressions appear.

## Risks

- **False skip risk**: prep/sync could be skipped when needed if drift detection
  is incomplete.
- **Locking risk**: single-flight implementation could accidentally serialize
  unrelated slugs or deadlock.
- **Log noise risk**: timing logs could add noise unless they stay structured
  and low-cardinality.
