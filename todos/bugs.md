# TeleClaude Bugs

## Blockers (Core Functionality Broken)

### [CRITICAL] Agent start command delivered to wrong TUI session

**Problem:** At unknown moments (likely during agent spawning or hook listener setup), a command to start an agent gets delivered to a running TUI session belonging to a different agent, causing the agent command to be executed inside another agent's terminal environment.

**Impact:**

- Silent session corruption - the TUI session receives unexpected shell commands
- Potential data loss or unexpected state changes
- Difficult to debug due to unpredictable timing

**Example manifestation:**

```
/Users/Morriz/Applications/ClaudeLauncher.app/Contents/MacOS/claude-launcher --dangerously-skip-permissions --settings '{"forceLoginMethod": "claudeai"}' --model haiku --resume 723a297b-8505-491a-a0ab-7803d507c18e
```

This command appears in running TUI sessions at random times.

**Root cause unknown** - suspects:

- Hook listeners forwarding to wrong session
- Session routing logic picking wrong target
- Telegram message routing bug
- MCP wrapper session context leak
- Adapter session mapping error

**Workaround:** None known. Issue occurs sporadically.

**Priority:** CRITICAL - Must investigate and fix before further development.

---

## High Priority (UX Issues)

### 1. Agent start slash commands fail with "unknown agent" in teleclaude sessions

**Steps to reproduce:**

1. Start a session via Telegram menu's "start session" button
2. Navigate to a project folder with `/cd` (working directory)
3. Call `/codex`, `/claude`, or `/gemini` command

**Expected:** Agent session starts with the specified agent type
**Actual:** Immediate feedback message: "unknown agent"

### 2. New session launches but tree selection does not update to active session

**Steps to reproduce:**

1. Select a project and start a new session
2. Observe the nested pane correctly shows the new session
3. Look at the tree view selection

**Expected:** The tree view auto-selects the newly launched session (the one currently shown)
**Actual:** Tree view selection remains on the previous node

### ~~4. Session title doesn't show active agent and mode~~ ✅ FIXED

**Fixed:** Session titles now show agent info when known:

- Agent unknown: `$Computer[project] - {title}` (uses `$` prefix)
- Agent known: `{Agent}-{mode}@Computer[project] - {title}` (e.g., `Claude-slow@MozMini`)
- AI-to-AI with agents: `{Initiator} > {Target}[project] - {title}`

Removed `AI:` prefix from AI-to-AI session titles. Title updates automatically when agent starts.

### 5. TUI screen jumps up one line on mouse click

**Steps to reproduce:**

1. Open telec TUI with sessions visible
2. Click on any tree node (computer, project, or session)
3. Observe the entire screen briefly jumps up ~1 line and back down

**Expected:** Screen stays stable; only the selection highlight changes
**Actual:** Whole screen scrolls up one line then recovers after ~150-200ms (matches ncurses click detection interval / mouseinterval — curses holds the BUTTON_PRESSED event for ~166ms to distinguish click from double-click, strongly suggesting the jump is caused by the raw PRESS event before curses delivers the CLICKED event)

**Notes:**

- Happens "most times" but not always
- Arrow key navigation does NOT trigger it
- The ENTIRE screen jumps (banner, tabs, content, footer), not just the content area
- Multiple investigation attempts ruled out: scroll_offset logic, curses scrollok/idlok/idcok/nonl settings, stray prints, bottom-right corner writes
- Next approach: add debug logging to observe exact state changes during click, and check if the jump correlates with tmux pane operations (preview activation)

### 6. Codex sessions never receive checkpoint injection

**Problem:** Codex only fires a single hook event (`agent-turn-complete` → `AGENT_STOP`). There is no equivalent of Claude's `PreToolUse` or Gemini's `AfterModel` that maps to `AFTER_MODEL`. Without `after_model` events, `last_after_model_at` is never set, and `_maybe_inject_checkpoint` always skips at rule 1 ("no after_model → text-only response").

**Evidence:** Logs show multiple `agent_stop` events for Codex session `1a77cbc2` over 15 minutes, zero `after_model` events, zero checkpoint injections.

**Fix direction:** For agents that lack `after_model` support, fall back to a simpler checkpoint policy — either skip the 30s threshold entirely, or use `last_activity` timestamps as a turn-start proxy.

---

## High Priority (Correctness / Observability)

### 3. Swallowing errors inside internal contract paths (must fail fast)

**Problem:** Internal code paths log warnings/errors and continue/return defaults, which hides contract violations and makes debugging impossible.

**Fix direction:**

- **Internal contract code must raise** (no log+continue / log+return).
- **External IO boundaries stay guarded** (Telegram/MCP/tmux/system stats/network).
- **No implicit fallbacks** for required fields (avoid `.get(...)` where a required value is expected).

**Priority order (internal-only swallowing to remove):**

1. `teleclaude/core/command_handlers.py`
   - Missing `native_log_file`, missing `active_agent`, missing session → currently log+return.
2. `teleclaude/core/agent_parsers.py`
   - Broad `try/except` during parse; currently logs and continues.
3. `teleclaude/utils/claude_transcript.py`
   - Parse errors logged and ignored; should raise.
4. `teleclaude/core/session_watcher.py`
   - Directory scan / tail errors logged and continued; should raise (internal contract).
5. `teleclaude/core/output_poller.py`
   - “Failed to read final output” warning; should raise (internal contract).

**Not in scope for this sweep (external IO guards to keep):**

- `teleclaude/adapters/telegram_adapter.py`
- `teleclaude/mcp_server.py`
- `teleclaude/core/terminal_bridge.py`
- `teleclaude/core/system_stats.py`
- `teleclaude/core/voice_message_handler.py`
- `teleclaude/core/session_cleanup.py`
- `teleclaude/core/file_handler.py`
- `teleclaude/utils/__init__.py` (retry wrappers)

**How to find more internal swallowing:**

- Grep for `try/except Exception` + `logger.warning|logger.error` + `return`/`continue`.
  Example:
  - `rg -n "try:|except Exception|logger\\.warning\\(|logger\\.error\\(" teleclaude -S`
- Grep for `.get(` on required fields in internal modules and replace with direct access + raise.
  Example:
  - `rg -n "\\.get\\(" teleclaude/core -S`
- Look for `logger.*` followed by `return` in internal modules under `teleclaude/core/`.
