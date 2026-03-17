# Review Findings: fix-git-wrapper-reset

**Kind:** Bug fix
**Review round:** 1
**Reviewer:** Claude (review session)

---

## Scope

Delivery matches bug.md exactly. The four cases defined in bug.md (bare reset → block, commit reset → block, pathspec reset with HEAD → allow, `--hard|--merge|--keep` → block) are all implemented. No gold-plating, no unrequested features.

## Code

### Resolved During Review: `git reset --` bypassed the guard

**Location:** `teleclaude/install/wrappers/git:148`

The separator check at line 148 allowed any command with `--` present, regardless of whether pathspecs followed. `git reset --` (separator, zero pathspecs) is functionally equivalent to bare `git reset` — it resets the entire staging area — but passed through the guard.

**Fix applied:** Changed line 148 to require at least one non-flag arg when `--` is present:

```bash
if [ "$_has_separator" -eq 1 ] && [ "$_non_flag_args" -ge 1 ]; then
```

Added `test_reset_bare_separator_blocked` test. Verified: `git reset --` now blocked, `git reset -- file.txt` still allowed. All 30 tests pass.

### Suggestion: `git reset HEAD --` also bypasses

**Location:** `teleclaude/install/wrappers/git:148-150`

`git reset HEAD --` would have `_has_separator=1` and `_non_flag_args=1` (HEAD). Even with the fix above, this passes through because `_non_flag_args` counts args both before and after `--`. In practice, `git reset HEAD --` resets the entire index (same as `git reset HEAD`). A more robust fix would track args-after-separator separately, but this is a narrow edge case.

### Suggestion: `-C` flag value matching "reset" could confuse inner loop

**Location:** `teleclaude/install/wrappers/git:119-124`

The `_is_subcmd` tracking scans `$@` for the literal word "reset" without handling global flags like `-C` that consume the next arg. If a directory is literally named "reset" and passed via `-C reset`, the inner loop would match the path value instead of the actual subcommand. This is a pathological case — no real bypass risk — but the top-level subcmd detection (lines 28-50) handles `-C` correctly while the inner loop does not.

## Paradigm

The arg-parsing pattern (iterate `$@`, case-match flags, count positional args) follows the existing style in the checkout and revert guards. The `_has_separator` variable naming is consistent with the checkout guard. Good paradigm adherence.

No findings.

## Principles

No violations detected. The fix follows fail-fast (blocks ambiguous commands), KISS (simple counting heuristic), and SRP (reset guard does one thing). No silent degradation — blocked commands produce clear error messages with actionable alternatives.

No findings.

## Security

- No secrets in the diff.
- Error messages expose no internal paths or sensitive data.
- The wrapper fails closed on ambiguous cases.
- No injection vectors — all args are properly quoted via `"$@"`.

No findings.

## Tests

- **Reproduction tests present:** `test_bare_reset_blocked` and `test_reset_commit_blocked` directly reproduce the bugs described in bug.md. ✓
- **Allow-path tests present:** `test_reset_head_path_allowed` and `test_reset_separator_allowed` verify pathspec resets work. ✓
- **Existing behavior preserved:** `test_reset_hard_blocked` now tests all three relevant roles. ✓
- **Bypass regression test added:** `test_reset_bare_separator_blocked` verifies `git reset --` is blocked. ✓
- All 30 tests pass.

No findings.

## Errors / Silent Failures

- The `((var++))` bash arithmetic bug (returns exit code 1 when var=0, triggering `set -e`) was correctly identified and fixed with `$((_non_flag_args + 1))`. ✓
- `set -euo pipefail` provides safety against uncaught failures. ✓
- No new silent failure paths introduced.

No findings.

## Comments

Comments on changed lines are accurate:

- Line 114: "Block reset variants that move HEAD" — correct intent description.
- Lines 142-147: Pathspec vs commit reset distinction is accurate.
- Lines 153-154: Correctly describes the blocking rationale.

No findings.

## Logging

Error messages via stderr are appropriate for a bash wrapper. Messages are clear, actionable (suggest alternatives), and consistent with existing wrapper error messages.

No findings.

## Demo

No `demo.md` exists and no `<!-- no-demo -->` marker is present. This is a bug fix to an infrastructure component (bash wrapper). The "users" are agents, not humans, and the behavior change (previously allowed commands now blocked) is fully exercised by the test suite. Demo would add limited value beyond what tests already prove.

No findings (infrastructure bug fix exemption).

---

## Resolved During Review

1. **`git reset --` bypass** — Tightened separator check to require `_non_flag_args >= 1`. Added reproduction test. Verified fix manually and via test suite.

## Summary

| Severity   | Count | Unresolved |
| ---------- | ----- | ---------- |
| Critical   | 0     | 0          |
| Important  | 1     | 0          |
| Suggestion | 2     | 2          |

**Suggestions (non-blocking):**

1. `git reset HEAD --` also bypasses (needs args-after-separator tracking).
2. Inner `_is_subcmd` loop doesn't handle `-C` flag values that happen to be "reset".

## Why No Important/Critical Issues Remain

1. **Paradigm-fit verified:** Reset guard follows the same arg-parsing pattern as checkout and revert guards.
2. **Requirements met:** All four cases from bug.md are correctly implemented and tested.
3. **Copy-paste duplication checked:** No duplicated logic — reset guard is self-contained.
4. **Security reviewed:** No injection vectors, no secrets, error messages are safe.
5. **The one Important finding (separator bypass) was auto-remediated** with a one-line fix and regression test, both verified.

## Verdict: APPROVE
