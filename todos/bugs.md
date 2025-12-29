# TeleClaude Bugs

## Blockers (Core Functionality Broken)

_None currently - all blockers fixed._

---

## High Priority (UX Issues)

### 1. Agent start slash commands fail with "unknown agent" in teleclaude sessions

**Steps to reproduce:**

1. Start a session via Telegram menu's "start session" button
2. Navigate to a project folder with `/cd` (working directory)
3. Call `/codex`, `/claude`, or `/gemini` command

**Expected:** Agent session starts with the specified agent type
**Actual:** Immediate feedback message: "unknown agent"

### ~~2. Session title doesn't show active agent and mode~~ ✅ FIXED

**Fixed:** Session titles now show agent info when known:

- Agent unknown: `$Computer[project] - {title}` (uses `$` prefix)
- Agent known: `{Agent}-{mode}@Computer[project] - {title}` (e.g., `Claude-slow@MozMini`)
- AI-to-AI with agents: `{Initiator} > {Target}[project] - {title}`

Removed `AI:` prefix from AI-to-AI session titles. Title updates automatically when agent starts.

---

## High Priority (Correctness / Observability)

### 3. Swallowing errors inside internal contract paths (must fail fast)

**Problem:** Internal code paths log warnings/errors and continue/return defaults, which hides contract violations and makes debugging impossible.

**Fix direction:**
- **Internal contract code must raise** (no log+continue / log+return).
- **External IO boundaries stay guarded** (Telegram/MCP/tmux/system stats/network).
- **No implicit fallbacks** for required fields (avoid `.get(...)` where a required value is expected).

**Priority order (internal-only swallowing to remove):**
1) `teleclaude/core/ux_state.py`
   - `get_session_ux_state` / `get_system_ux_state` swallow invalid JSON / DB errors.
2) `teleclaude/core/command_handlers.py`
   - Missing `native_log_file`, missing `active_agent`, missing session → currently log+return.
3) `teleclaude/core/agent_parsers.py`
   - Broad `try/except` during parse; currently logs and continues.
4) `teleclaude/utils/claude_transcript.py`
   - Parse errors logged and ignored; should raise.
5) `teleclaude/core/session_watcher.py`
   - Directory scan / tail errors logged and continued; should raise (internal contract).
6) `teleclaude/core/output_poller.py`
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
