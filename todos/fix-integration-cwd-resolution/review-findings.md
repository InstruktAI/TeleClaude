# Review Findings: fix-integration-cwd-resolution

**Ad-hoc review (via from-main)**

## Resolved During Review

### 1. [Important] Relative path resolution bug in cwd worktree detection — `state_machine.py:75`

**Was:** `git rev-parse --git-common-dir` returns a relative path (`.git`) when run
from the repo root but an absolute path from worktrees. The code used
`Path(output).resolve().parent` which resolves relative paths against the Python
process's `os.getcwd()` — not the `cwd` parameter passed to the function. If the
daemon's process cwd differs from the passed `cwd`, this would resolve to the wrong
directory.

**Fix:** Added `--path-format=absolute` flag (already used in `scripts/distribute.py`)
to guarantee git returns an absolute path regardless of context. Removed `.resolve()`
since it's no longer needed. Updated comment to explain the flag.

### 2. [Important] No test coverage for cwd resolution logic — `state_machine.py:72-80`

**Was:** The blanket `_run_git` mock in existing tests returned `(0, "", "")`, making
the cwd resolution a silent no-op. The primary bug fix had zero test coverage.

**Fix:** Added `test_dispatch_resolves_worktree_cwd_to_repo_root` with a command-aware
mock that returns a realistic absolute git dir path for `--git-common-dir`. Verifies
all subsequent git calls use the resolved repo root.

### 3. [Important] No test coverage for orphaned state.yaml fix — `step_functions.py:783`

**Was:** The removal of `_mirror_integration_phase` from `_do_cleanup` was unverified.
The existing test (`test_repo_root_pull_success_continues_to_cleanup`) blanket-patched
`_mirror_integration_phase` but never asserted it wasn't called.

**Fix:** Captured the mock and added `mock_mirror.assert_not_called()` assertion to
guard against reintroduction of the orphaned state.yaml bug.

## Code Lane

No unresolved findings. The exception logging wrappers (log-and-reraise) follow
established patterns and preserve error propagation.

## Paradigm Lane

No findings. Logger usage via `get_logger(__name__)` is consistent. Git operations
use the existing `_run_git` helper. Comment style matches codebase conventions.

## Principles Lane

No findings. The cwd resolution fallback (use original cwd when git fails) is
appropriate — downstream `git pull` surfaces the real error. The removed
`_mirror_integration_phase` call was a genuine bug fix, not a fallback removal.

## Security Lane

No findings. No secrets in diff. Logger messages contain only operational
identifiers (slug, cwd, session_id). Subprocess uses list args (no injection).
Error messages are internal server logs, not returned to users.

## Tests Lane

All coverage gaps resolved during review. 10 tests pass (3 new assertions total).

## Errors Lane (Silent Failures)

No findings. The cwd resolution fallback is appropriate (preserves previous
behavior; downstream operations fail explicitly). The log-and-reraise wrappers
add observability without swallowing errors.

## Comments Lane

Both new comments are factually accurate. The `--git-common-dir` comment was
updated to document the `--path-format=absolute` flag. The orphaned state.yaml
comment correctly describes the failure chain (cleanup deletes directory,
mirror would recreate it).

## Logging Lane

No findings. Uses appropriate levels (`info` for operational events, `exception`
for errors with tracebacks). %-style formatting consistent with codebase.

## Types Lane

No type changes in scope. Not applicable.

## Simplify Lane

No simplification opportunities. Changes are minimal and targeted.

## Verdict

**APPROVE**

Critical: 0
Important: 0 (3 resolved during review)
Suggestions: 0
