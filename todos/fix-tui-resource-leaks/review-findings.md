# Review Findings: fix-tui-resource-leaks

**Ad-hoc review (via from-main)**

## Resolved During Review

### 1. `_chiptunes_reconcile_task` not nulled on natural completion — Important

**File:** `teleclaude/cli/tui/app_media.py:185-192`

When `_reconcile()` completed normally, `_chiptunes_reconcile_task` still held a reference to
the finished Task. Inconsistent with the `_sky_width_timer` and `_state_save_timer` patterns
which null themselves in callbacks.

**Fix:** Added `finally` block in `_reconcile` to null `_chiptunes_reconcile_task` on completion.

### 2. `_sky_width_timer: object | None` — wrong type — Important

**File:** `teleclaude/cli/tui/app.py:164`

`object | None` erased the Timer contract, forcing `hasattr(timer, "stop")` duck-typing guards
and `# type: ignore[union-attr]` suppressions at every call site.

**Fix:** Changed to `Timer | None` (imported under TYPE_CHECKING), removed `hasattr` guards
and type suppressions from `_schedule_sky_width_invalidation` and `_cancel_sky_width_timer`.

### 3. Missing docstrings on new methods — Suggestion

**Fix:** Added concise docstrings to `_schedule_sky_width_invalidation`,
`_cancel_sky_width_timer`, `_schedule_chiptunes_reconcile`, and `on_unmount`.

### 4. No tests added for new behavior — Important

**Files:** All three changed files.

Zero tests existed for the new methods. The existing test for `_schedule_chiptunes_reconcile`
in `test_app_media.py` mocked it away entirely, so the debounce logic was never exercised.

**Fix:** Added `tests/unit/cli/tui/test_resource_cleanup.py` with 11 tests covering:

- `_schedule_chiptunes_reconcile` task storage, cancel-before-create debounce, null on completion
- `_cancel_chiptunes_reconcile` no-op when None, cancels active task
- `_schedule_sky_width_invalidation` timer storage, stops previous timer
- `_cancel_sky_width_timer` no-op when None, stops and nulls
- `SessionsView.on_unmount` bulk timer cleanup, empty dict no-op

### 5. Broad `except Exception` at debug level in reconcile — Important (pre-existing)

**File:** `teleclaude/cli/tui/app_media.py:189-190`

The `_reconcile` inner function caught `except Exception` and logged at DEBUG level, swallowing
all non-BaseException errors including bugs in `_apply_chiptunes_status`. Debug level is
typically disabled in production.

**Fix:** Raised log level to WARNING so reconcile failures are visible in production.

## Lanes Executed

- **scope**: Skipped (ad-hoc review)
- **code**: Executed — 1 Important finding (resolved)
- **paradigm**: Executed — no findings (pattern matches existing `_state_save_timer`)
- **principles**: Executed — no violations
- **security**: Executed — no findings
- **tests**: Executed — 1 Important finding (resolved)
- **errors**: Executed — 2 Important findings (both resolved)
- **types**: Executed — 1 Important finding (resolved)
- **comments**: Executed — suggestions only (resolved)
- **logging**: Executed — no new logging issues (pre-existing broadened to WARNING)
- **demo**: Skipped (ad-hoc review)
- **simplify**: Not applicable (no surplus complexity)

## Suggestions (non-blocking)

- Pre-existing `_state_save_timer: object | None` at `app.py:159` has the same typing issue.
  Follow-up to convert all `object | None` timer/trigger fields to proper types.
- Pre-existing 61 `# type: ignore[attr-defined]` in `app_media.py` from mixin pattern.
  A `Protocol` defining the host contract would eliminate all suppressions.

## Why No Unresolved Issues

1. **Paradigm-fit verified**: Timer cancel pattern mirrors existing `_state_save_timer` pattern.
2. **Requirements met**: All three resource leak categories (fire-and-forget tasks, untracked
   timers, unmount cleanup) are addressed with proper lifecycle management.
3. **Copy-paste checked**: `_schedule_sky_width_invalidation` and `_cancel_sky_width_timer`
   extracted from inline `set_timer` calls — no duplication.
4. **Security reviewed**: No secrets, no injection, no sensitive data in logs.

## Verdict

**Critical:** 0
**Important (unresolved):** 0

**APPROVE**
