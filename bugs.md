# TeleClaude Bugs

## Blockers (Core Functionality Broken)

_None currently - all blockers fixed._

---

## High Priority (UX Issues)

_None currently - all high priority issues fixed._

---

## Fixed (Keep for Reference)

### 1. Voice Input Not Working

**Status:** FIXED
**Severity:** BLOCKER
**Fixed:** Dec 3, 2025
**Introduced:** Commit `e9972de` (Dec 3, 2025) - "feat(listeners): add PUB-SUB session listener mechanism"

**Symptoms:**
- Voice messages sent in forum topics were silently ignored
- No transcription, no feedback to user

**Root Cause:**
The `filters.ChatType.SUPERGROUP` filter was re-added in commit `e9972de` during a refactor. This filter does NOT match messages in forum topic threads (Telegram quirk). The original fix in `81a9473` specifically removed this filter.

**Fix:**
Removed `& filters.ChatType.SUPERGROUP` from the voice handler in `teleclaude/adapters/telegram_adapter.py`.
Added comment explaining why this filter must NOT be used.

**Files:** `teleclaude/adapters/telegram_adapter.py`

---

### 2. pending_deletions Not Cleared on Session End

**Status:** FIXED
**Severity:** HIGH (data accumulation, cosmetic)
**Fixed:** Dec 3, 2025

**Symptoms:**
- Old user messages remained in Telegram after session closed
- Database accumulated stale `pending_deletions` entries

**Root Cause:**
`pending_deletions` were only cleared by `_pre_handle_user_input()`, which runs when the user sends their **next** message. If a session ended without the user sending another message, the pending messages were never deleted.

**Fix:**
Added cleanup of `pending_deletions` and `pending_feedback_deletions` in `cleanup_session_resources()`:
```python
await db.clear_pending_deletions(session_id)
await db.update_ux_state(session_id, pending_feedback_deletions=[])
```

**Files:** `teleclaude/core/session_cleanup.py`

---

### 3. New Session Button - No User Feedback

**Status:** FIXED
**Severity:** HIGH (confusing UX)
**Fixed:** Dec 3, 2025

**Symptoms:**
- User clicked "🚀 Terminal Session" button in heartbeat message (General topic)
- Session was created successfully but user had no indication where it was
- Only ephemeral popup "Creating session..." that disappeared after ~5 seconds

**Fix:**
After session creation, now sends a confirmation message in General topic with a clickable "Open Session" button linking directly to the new topic.

**Files:** `teleclaude/adapters/telegram_adapter.py`

---

### 4. Duplicate Summary Messages ("Work complete!")

**Status:** FIXED
**Severity:** HIGH (spam, UX annoyance)
**Fixed:** Dec 3, 2025

**Symptoms:**
- Multiple "Work complete!" messages accumulating in Telegram for a single Claude session
- Example: 6 identical summary messages sent in 11 minutes
- Messages should be cleaned up but weren't

**Root Cause:**
Claude Code fires **multiple Stop hook events** for the same session even when no new work was done. Each Stop event triggered the summarizer and sent a new summary message.

**Fix:**
Added deduplication logic in `.claude/hooks/teleclaude_bridge.py`:
- Track transcript file's `mtime` per session in `bridge_state.json`
- On Stop event, compare current `mtime` to last processed
- Skip summary if transcript unchanged since last summary
- Stop event still forwarded (for listener notifications), only summary suppressed

**Files:** `.claude/hooks/teleclaude_bridge.py`

---

## Summary

| Bug | Severity | Status | Files |
|-----|----------|--------|-------|
| Voice filter regression | BLOCKER | FIXED | telegram_adapter.py |
| pending_deletions leak | HIGH | FIXED | session_cleanup.py |
| Session button UX | HIGH | FIXED | telegram_adapter.py |
| Duplicate summaries | HIGH | FIXED | teleclaude_bridge.py |
