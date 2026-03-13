# Review Findings: fix-state-machine-triggers-unnecessary-revie

## Summary

Bug fix moves `finalize_state` read before the stale review guard and adds a
`finalize_status not in ("ready", "handed_off")` condition to skip the stale
check when finalize is already in progress. The fix is correct, minimal, and
well-documented in bug.md. Two gaps remain.

## Critical

1. **Missing reproduction test** — `core.py:4398-4405`
   Bug fix policy requires a test that reproduces the bug (RED) before the fix,
   which becomes a permanent regression guard. No test file was added or modified.
   The scenario to cover: state with `review=APPROVED`,
   `finalize.status=ready`, `review_baseline_commit != HEAD`, and
   `_has_meaningful_diff` returning True — verify that review is NOT reset to
   PENDING. Currently `next_work()` has zero direct test coverage, so a focused
   helper extraction or async integration test is needed.

## Important

_(none)_

## Suggestions

1. **Demo artifact missing** — No `demo.md` exists. For a pure internal state
   machine ordering fix with no user-visible behavior change, a
   `<!-- no-demo: reason -->` marker is acceptable. Consider adding one for
   artifact completeness.

2. **Minor inconsistency in finalize_status default** — Line 4404 reads
   `finalize_state.get("status", "pending")` with explicit default, while lines
   4432 and 4440 read `finalize_state.get("status")` without default. Not
   functionally different (None fails the equality checks naturally), but
   consistency would improve readability.

## Scope Verification

- Bug.md symptom: state machine triggers unnecessary review round after finalize
  merges main. ✓ Fix addresses exactly this.
- Bug.md suggested approach: add `review_before_finalize_sha` checkpoint. Actual
  fix is simpler — skip stale check when finalize is already ready/handed_off.
  This is a better design (less state, same correctness). ✓

## Code Quality

- The moved line (`finalize_state = _get_finalize_state(state)`) is a pure read
  with no side effects — safe to hoist. ✓
- The guard condition `finalize_status not in ("ready", "handed_off")` correctly
  targets the two post-finalize states where merge-main commits appear. ✓
- Comment at lines 4400-4403 accurately explains the rationale. ✓

## Security

No security implications — internal state machine logic with no user input,
secrets, or I/O changes.

## Principle Violation Hunt

- No unjustified fallbacks introduced. ✓
- No DIP violations. ✓
- No coupling issues. ✓
- Follows KISS — minimal change for the root cause. ✓

## Why One Critical Finding

The code fix itself is correct and well-reasoned. The Critical finding is
process-based: bug fix policy mandates a reproduction test as a permanent
regression guard. The stale review guard has zero test coverage, making this
ordering-sensitive logic vulnerable to future refactors.

## Fixes Applied

| # | Finding | Fix | Commit |
|---|---------|-----|--------|
| C1 | Missing reproduction test | Added `test_stale_review_guard.py` with 3 tests: finalize-ready skips reset, finalize-pending allows reset (counter-test), finalize-handed_off skips reset. All pass. | fafa09b38 |

## Verdict

**APPROVE** — All Critical findings resolved. C1 fixed in fafa09b38; 3 regression tests pass.
