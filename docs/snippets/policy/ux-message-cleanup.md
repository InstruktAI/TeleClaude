---
id: policy/ux-message-cleanup
type: policy
scope: project
description: Automatic cleanup of Telegram message clutter for a clean UI.
---

# UX Message Cleanup Policy

## Purpose
Prevents message accumulation in Telegram topics to maintain a clear, focused workspace for both humans and AI.

## Cleanup Flows
1. **User Input Cleanup**: Old user messages are deleted when the next input is received in the same session.
2. **Feedback Cleanup**: Previous AI status/summary messages are deleted before sending a new feedback message.
3. **Dual Tracking**:
   - `user_input`: Tracked for deletion on next input.
   - `feedback`: Tracked for deletion on next feedback.

## Invariants
- **AI Results**: Persistent AI results (e.g., Markdown reports) are NEVER deleted.
- **File Artifacts**: Files uploaded by agents are NEVER deleted.
- **Tracking Required**: Developers MUST use tracking APIs (`db.add_pending_deletion`) instead of raw `reply_text`.
