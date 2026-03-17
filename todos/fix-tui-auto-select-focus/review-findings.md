# Review Findings: fix-tui-auto-select-focus

**Ad-hoc review (via from-main)**

**Review round:** 1
**Commit reviewed:** 1c22f01c7 `fix(tui): unify session auto-select with focus intent`

---

## Critical

No findings.

## Important

No findings.

## Suggestions

### S1: Orphaned `_pending_select` on revive failure

**File:** `teleclaude/cli/tui/views/sessions.py:498-506`

`_revive_headless` now calls `request_select_session` before posting `ReviveSessionRequest`. If the
API call fails in `app_actions.py`, the pending selection remains set with no cleanup path. The state
leak is bounded — any subsequent user selection action overwrites it, and the per-update scan returns
early when no tmux pane exists — but a timeout or failure-message cleanup would be more correct.

### S2: `_revive_headless` docstring omits auto-select side effect

**File:** `teleclaude/cli/tui/views/sessions.py:499`

Docstring says "Request revive for a headless session" but the method now also registers a pending
auto-select via `request_select_session`. The side effect is architecturally significant.

### S3: `_pending_select` inline comment could mention focus intent

**File:** `teleclaude/cli/tui/views/sessions.py:124-125`

Comment says "session to select+preview once it appears" but omits the focus-intent dimension that
this entire changeset introduces.

### S4: Ambiguous double-use of "focus" in comment

**File:** `teleclaude/cli/tui/views/sessions_actions.py:135`

Comment `# Headless sessions: revive instead of focus (Enter = focus)` uses "focus" in two different
senses. Could be clarified to distinguish the immediate focus path from deferred auto-focus.

### S5: Missing `logger.exception` in revive handler (pre-existing)

**File:** `teleclaude/cli/tui/app_actions.py:124-125`

The `except Exception` block shows a toast but never logs the traceback. Compare with
`on_restart_sessions_request` at line 143 which uses `logger.exception()`. Pre-existing but directly
impacts the changed revive flow.

---

## Lanes Executed

| Lane       | Trigger       | Result                                                                                   |
| ---------- | ------------- | ---------------------------------------------------------------------------------------- |
| code       | Always        | No findings                                                                              |
| paradigm   | Always        | No findings — follows existing patterns (NamedTuple, message-passing, WS-driven updates) |
| principles | Always        | No findings — immutable NamedTuple, clean API, no fallbacks, no DIP violations           |
| security   | Always        | No findings — pure UI state management, no user input, no secrets                        |
| tests      | Always        | Adequate — core `_apply_pending_selection` has full branch coverage with focus variants  |
| errors     | Always        | S1 (bounded state leak on failure path)                                                  |
| comments   | Changed code  | S2, S3, S4                                                                               |
| logging    | Always        | S5 (pre-existing missing logger.exception)                                               |
| types      | Not triggered | No new types beyond `_PendingSelect` which is well-designed                              |

## Why No Issues

1. **Paradigm-fit verified:** The change uses `NamedTuple` for structured state (consistent with
   Python conventions), keyword-only `request_focus` parameter (consistent with existing
   `PreviewChanged` pattern), and WS-driven updates replacing sleep-based polling.

2. **Requirements met:** Focus intent correctly threads from user action (Space/Enter/click/WS
   new-session) through `_PendingSelect` to `PreviewChanged.request_focus`. The semantic distinction
   (Space = no focus, Enter/click = focus) is preserved at every call site.

3. **Copy-paste duplication checked:** No duplicated logic. `_revive_headless` is the single entry
   point for revive + auto-select. All callers use it consistently.

4. **Security reviewed:** No secrets, injection vectors, or sensitive data in the diff. Pure UI state.

5. **Test coverage verified:** 7 tests pass. Core method has full branch coverage (no pending, not in
   tree, in tree no pane, in tree ready) with both `request_focus=True` and `request_focus=False`
   variants. Two new tests specifically target the focus intent feature.

---

## Verdict: APPROVE
