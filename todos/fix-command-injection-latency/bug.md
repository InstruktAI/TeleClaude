# Bug: Agent command injection latency (~5s+) and silent failures after f68946b47

## Symptom

Agent command injection latency (~5s+) and silent failures after f68946b47

## Detail

## Symptom

- ~5s+ latency after agent output goes idle before final state is visible
- Spurious artifacts from extra Enter keystrokes injected into running agents
- Failed command injections silently swallowed — user never notified

## Root Causes

### Issue 1: Spurious Enter keys — daemon_session.py:621-650

`_confirm_command_acceptance` runs AFTER `process_text` already sent the command with `send_enter=True` (line 488). It sends up to 8 additional Enter keys (2 per attempt × 4 attempts) with a 2.5s output change timeout per attempt and 1.0s sleep between attempts. Worst case: ~14s of spurious keystrokes into a running agent.

**Fix:** Delete `_confirm_command_acceptance` and its constants (`AGENT_START_CONFIRM_ENTER_ATTEMPTS`, `AGENT_START_OUTPUT_CHANGE_TIMEOUT_S`, `AGENT_START_ENTER_INTER_DELAY_S`, `AGENT_START_CONFIRM_ENTER_DELAY_S`). Also delete `_wait_for_output_change` (becomes dead code).

### Issue 2: Idle flush 3.0s tax — output_poller.py:160

Hardcoded `>= 3.0` second wait after output stops changing before flushing. Re-sends identical content. Pure latency on every turn completion.

**Fix:** Reduce to one poll interval — if output hasn't changed since last check, one tick confirms idle.

### Issue 3: Errors silently swallowed — daemon_session.py:357-378

`_handle_agent_then_message` returns `{"status": "error"}` dicts. `_execute_auto_command` stores in `auto_command_result` and ignores it — session transitions to `"active"` regardless. Line 467-472: timeout explicitly logs warning and "proceeds anyway."

**Fix:** Check result, close session on error, notify user via adapter.

### Issue 4: Fragile text-based markers — daemon_session.py:75-78

Current markers are text content: `"❯ "` (Claude), `"Type your message or @path/to/file"` (Gemini), `"? for shortcuts"` (Codex). Break on any agent CLI update.

**Fix:** Use structural box-drawing characters (confirmed via live tmux captures):
- Claude: `─` (U+2500) repeated line — input box border
- Gemini: `▀` (U+2580) / `▄` (U+2584) repeated lines — input box borders
- Codex: `›` (U+203A) prompt character

### Issue 5: Settle + marker must be AND, not OR — daemon_session.py:381-413

`_wait_for_agent_prompt_ready` tries marker first, falls back to settle. But all three agents render the input box during active processing (confirmed via live capture of all three). Marker alone doesn't mean ready. Settle alone doesn't confirm prompt is showing.

**Fix:** Wait for output to settle (stop changing), THEN verify structural marker is present. Both gates required.

## Evidence

Live tmux captures of all three agents at idle and during processing:
- Claude: `───` border lines with `❯` between them, present during active work
- Gemini: `▀▀▀` / `▄▄▄` border lines with ` *   Type your message...` between them
- Codex: `›` prompt with `? for shortcuts` footer, no box borders

## Files to modify

- `teleclaude/daemon_session.py` — issues 1, 3, 4, 5
- `teleclaude/core/output_poller.py` — issue 2
- `tests/unit/test_daemon_session.py` — update tests for changed methods

## Introduced by

Commit f68946b47 ("replace inactivity readiness with agent-specific prompt markers")

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-19

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
