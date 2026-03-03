# Requirements: state-machine-gate-sharpening

## Goal

Eliminate false-invalidation loops in the `next_work` state machine that burn review rounds,
force unnecessary full rebuilds, and block finalize — three targeted fixes in
`teleclaude/core/next_machine/core.py`.

## Scope

### In scope

- Merge-aware stale baseline guard (fix 1)
- Preserve build status on gate failure after review (fix 2)
- Single retry for low-count flaky test failures in `run_build_gates` (fix 3)
- Unit tests for all three behaviors

### Out of scope

- Changes to the review workflow itself
- Changes to `mark_phase` semantics
- Changes to demo validation logic
- Changes to artifact verification logic
- Flaky test root cause (the async teardown pattern itself)

## Success Criteria

- [ ] **SC-1**: When review is approved and only merge commits / `todos/` / `.teleclaude/` files
      differ between baseline and HEAD, review approval holds (no invalidation).
- [ ] **SC-2**: When review is approved and a non-infrastructure commit touches files outside
      `todos/` and `.teleclaude/`, review is correctly invalidated to pending.
- [ ] **SC-3**: When build gates fail and `review_round > 0`, build status stays `complete`
      (not reset to `started`).
- [ ] **SC-4**: When build gates fail and `review_round == 0` (first build), build status
      resets to `started` (existing behavior preserved).
- [ ] **SC-5**: When `make test` fails with ≤2 test failures, `run_build_gates` retries the
      failing tests once with `pytest --lf`. If retry passes, gate passes.
- [ ] **SC-6**: When `make test` fails with >2 test failures, no retry — gate fails immediately.
- [ ] **SC-7**: When retry also fails, gate fails with combined output from both runs.

## Constraints

- All changes confined to `teleclaude/core/next_machine/core.py`.
- No new dependencies.
- `git diff --name-only` call must use the worktree cwd and handle subprocess errors gracefully.
- The retry mechanism must parse pytest output format to count failures (`N failed`).
- The retry must run `pytest --lf` in the worktree with the same environment as `make test`.

## Risks

- Pytest output format for failure counts may vary across versions — parser must be lenient.
- `git diff --name-only` across merge commits may include merge-introduced files; filtering
  must handle both fast-forward and true merge scenarios.
