# Review Findings: fix-integration-state-machine-infinite-loop-2

## Verdict: APPROVE

All Important findings were resolved during review. No Critical findings.

---

## Resolved During Review

### 1. [Important → Resolved] Missing tests for `_ensure_integration_worktree` merge state detection

**Location:** `teleclaude/core/integration/step_functions.py:165-176`

The third fix area (MERGE_HEAD / SQUASH_MSG guards that skip `git reset --hard`) had zero test
coverage. Added `tests/unit/core/integration/test_worktree_guards.py` with four tests:

- `test_skips_reset_when_merge_head_exists` — active merge skips fetch + reset
- `test_skips_reset_when_squash_msg_exists` — in-progress squash skips reset
- `test_skips_reset_when_git_dir_unresolvable` — fail-safe when git dir unknown
- `test_proceeds_with_reset_when_no_merge_state` — normal path proceeds with sync

### 2. [Important → Resolved] `_git_dir` returning None silently disabled SQUASH_MSG guard

**Location:** `teleclaude/core/integration/step_functions.py:170-174`

When `_git_dir` returned `None`, the SQUASH_MSG check was silently skipped, falling through to
`git reset --hard` — the exact data destruction the guard was built to prevent. Changed to
fail-safe: when `_git_dir` returns `None`, skip reset instead of proceeding.

### 3. [Important → Resolved] Stale docstring on `_try_auto_enqueue`

**Location:** `teleclaude/core/integration/step_functions.py:246-258`

The docstring described only the ancestry check as the re-enqueue prevention mechanism. Updated
to document the new primary guard (queue-presence check for any status) and the ancestry check
as the secondary guard.

### 4. [Important → Resolved] Missing `blocked`/`superseded` auto-enqueue tests

**Location:** `tests/unit/core/integration/test_auto_enqueue.py`

The behavioral contract changed to "skip for ANY existing entry" but only `queued`,
`in_progress`, and `integrated` were tested. Added `test_auto_enqueue_skips_blocked_item` and
`test_auto_enqueue_skips_superseded_item` to cover all five `QueueStatus` values.

---

## Suggestions (unresolved, non-blocking)

### S1. Broad `except Exception` on `mark_integrated` in `state_machine.py:217-220`

Now that `queued → integrated` is valid, the broad catch hides different (more serious) errors
than before (e.g., `OSError` from disk corruption, `IntegrationQueueError` for unknown
candidates). Consider narrowing to `except IntegrationQueueError`.

Pre-existing pattern — not introduced by this diff.

### S2. Duplicate `mark_integrated` calls

`mark_integrated` is called in both `_do_cleanup` (step_functions.py:698) and the
`CANDIDATE_DELIVERED` handler (state_machine.py:218). The second call relies on idempotency
guards. Consider centralizing to one call site.

Pre-existing pattern — not introduced by this diff.

### S3. `_merge_head_exists` conflates "no merge" with "git-dir lookup failed"

`_merge_head_exists` returns `False` when `_git_dir` returns `None`, conflating "no active
merge" with "cannot determine state." Same structural issue as Finding 2, but for MERGE_HEAD
(less likely to be the sole merge state indicator for squash merges).

Pre-existing pattern — not introduced by this diff.

### S4. Missing demo artifact

No `demo.md` exists. This is a pure internal bug fix with zero user-visible behavior change
(no CLI, TUI, config, API, or messaging changes). A `<!-- no-demo: reason -->` marker
would make the intent explicit but is not blocking for an internal state machine fix.

---

## Scope Verification

All three changes in `bug.md` "Fix Applied" are present in the diff:
1. ✅ `queue.py`: `queued → integrated` transition added
2. ✅ `step_functions.py _try_auto_enqueue`: guard broadened to any queue status
3. ✅ `step_functions.py _ensure_integration_worktree`: merge state detection added

No gold-plating. No unrequested features.

## Paradigm-Fit

- Transition table approach follows established queue.py pattern
- Guard pattern in step_functions.py matches adjacent guards (ancestry check, SHA validation)
- Test structure follows existing `tests/unit/core/integration/` patterns

## Security

No secrets, injection risks, auth gaps, or info leakage in the changed code.

## Why Approved

1. Paradigm-fit verified: transition table, guard pattern, test patterns all match codebase conventions.
2. Requirements met: all three bug.md fix items implemented and tested.
3. Copy-paste duplication checked: no duplicated logic introduced.
4. Security reviewed: no secrets, injection, or auth issues in diff.
5. All Important findings were auto-remediated and validated (13 tests passing).
