# Quality Checklist: Bug cleanup pipeline has three gaps

## Code Quality

- [x] Changes are minimal and surgical — no unnecessary refactoring
- [x] All three fixes target specific functions at exact line numbers
- [x] No hidden side effects introduced
- [x] Error handling preserved where it exists
- [x] Contract fidelity maintained across all three fixes

## Testing

- [x] Tests pass: `make test`
- [x] Lint passes: `make lint`
- [x] No new warnings or errors introduced
- [x] Pre-commit hooks enforced

## Documentation

- [x] bug.md updated with Investigation, Root Cause, and Fix Applied sections
- [x] implementation-plan.md created documenting each gap and its fix
- [x] Fixes correspond exactly to the three identified gaps

## Commit Quality

- [x] Single logical changeset covering all three fixes
- [x] Commit message explains WHY (three independent defects in bug cleanup)
- [x] No debug code or temporary changes included
- [x] No unrelated files in the commit

## Bug Lifecycle Verification

- [x] Gap 1: _is_bug_slug() path corrected from `todos/bugs/{slug}/bug.md` to `todos/{slug}/bug.md`
- [x] Gap 2: deliver_to_delivered() now handles slugs with no roadmap entry
- [x] Gap 3: remove_todo() now handles worktree removal best-effort

## Integration Impact

- [x] Bug slugs can be correctly detected by the integration machine
- [x] Bug slugs can be delivered to delivered.yaml without roadmap entries
- [x] Bug slugs can be fully removed through CLI despite active worktrees
- [x] No breaking changes to existing workflows

## Build Gates

- [x] `make test` passes — all unit and integration tests pass
- [x] `make lint` passes — no style, type, or linting errors
- [x] Pre-commit hooks pass — formatting, imports, and code quality checks enforced
- [x] No new warnings or errors in CI pipeline
- [x] Git history clean — single atomic commit with clear message

## Sign-off

All quality gates met. Ready for review.
