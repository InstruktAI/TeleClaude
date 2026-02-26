# Requirements: api-todos-work-stability-hardening

## Goal

- Reduce `/todos/work` request-path latency and watchdog noise by removing redundant expensive work, while preserving existing orchestration behavior and safety checks.

## Scope

- In scope:
- Add phase-level timing/trace logs for `next_work(...)` critical sections (resolution, prep, sync, precondition checks, gates).
- Ensure worktree preparation does not rerun redundantly for unchanged worktrees.
- Prevent duplicate concurrent prep work for the same slug.
- Preserve and verify current correctness guarantees (drift recovery, dependency checks, phase transitions, build/review/finalize flow).
- Add/adjust tests that cover prep/sync skip conditions and single-flight behavior.
- Out of scope:
- Replacing `aiosqlite` or changing database backend.
- Host service manager changes, launchctl/systemd changes, or infra-level daemon changes.
- Broad redesign of next-machine flow unrelated to `/todos/work` latency.
- Blind watchdog-threshold tuning without supporting phase metrics.

## Success Criteria

- [ ] Repeated `/todos/work` calls for an unchanged prepared slug do not rerun worktree prep on every call.
- [ ] Phase timing logs clearly identify where request-path time is spent for `/todos/work`.
- [ ] Existing next-work behavior remains functionally correct (no regressions in gating, state transitions, dependency checks).
- [ ] Test coverage exists for skip/prepare decision logic and concurrent-call behavior.

## Constraints

- Must keep API and CLI-facing behavior compatible unless explicitly approved.
- Must not reduce safety by skipping prep when drift or dependency changes require it.
- Must avoid introducing global locks that serialize unrelated slug work.

## Risks

- False negatives in drift detection could skip needed prep and cause hard-to-debug failures.
- Single-flight coordination bugs could deadlock or starve calls under contention.
- Additional logging could become noisy without clear structure.
