# Roadmap

## 1. [x] Notifications

Create claude code "notification" hook that sends informative feedback message to the channel/topic via adapter_client.send_message. Look at /Users/Morriz/.claude/hooks/notification.py for inspiration. Imperative is that we use a bootstrapped adapter_client like in daemon.py, as it has all the UiAdapters wired up so they recieve notificaitons. The message can just be randomized out of a set of templates like "Claude is ready...", "Claude is back baby...", "Claude reporting back for duty...", etc. Make like 15 nice ones. Important side note: we keep an inactivity timer, which should be compleetely nuked once that message is sent. I dont know how to signal that to daemon, but I think its best to keep the state in ux_state blob in the db, so you should make daemon check that flag (inside the inactivity timer loop?).

## 2. [x] REST API: Notification Endpoint for Claude Code Hooks

**Problem**: Current notification.py hook bootstraps the entire TeleClaude daemon (database, adapters, event loops) just to send one message. This causes Claude Code to hang because the hook process never completes - the Telegram adapter's event loop blocks indefinitely.

**Solution**: Add REST API endpoint to allow lightweight HTTP calls from hooks to the already-running daemon.

**Tasks**:
- [ ] Add `POST /api/v1/notifications` endpoint to `rest_api.py`
  - Input: `{session_id, message, claude_session_file?}`
  - Creates Telegram topic if needed (via AdapterClient)
  - Sends message via AdapterClient.send_message()
  - Sets `notification_sent=True` flag in ux_state
  - Returns: `{success: true, message_id: "..."}`
- [ ] Rewrite `.claude/hooks/notification.py` to use HTTP:
  - Remove bootstrap_teleclaude() and all TeleClaude imports
  - Simple `requests.post("http://localhost:6666/api/v1/notifications", json={...})`
  - Returns immediately (no hanging)
- [ ] Add `DELETE /api/v1/sessions/{session_id}/notification_flag` endpoint
  - Clears notification_sent flag
  - Used by stop.py hook to re-enable idle notifications
- [ ] Update `.claude/hooks/stop.py` to use HTTP API instead of bootstrapping

**Benefits**:
- Fast, lightweight hooks (~100ms vs 5+ seconds)
- No hanging/blocking
- No duplicate daemon startup
- Clean separation: hooks are thin clients, daemon does the work

## 3. [ ]
