# Claude Code Native Session Logging

**Status:** Implementation Plan
**Created:** 2025-11-11
**Priority:** HIGH

## Problem

Claude Code sessions generate massive output files (516KB+) because we capture entire tmux pane every second, including TUI redraws. The actual conversation is buried in noise.

Claude Code already maintains perfect session files (`.jsonl`) with structured conversation history. **We should use those instead!**

## Solution: Detect → Extract → Transform → Load

### 1. Detect Claude Running

**When:**
- `get_current_command()` returns `"claude"`

**Find Session File:**

```python
# Option A: Scan filesystem for active .jsonl (most reliable)
def find_claude_session_file(project_dir: str) -> Optional[str]:
    """Find active Claude session file in project directory."""
    claude_dir = Path.home() / ".claude" / "projects"

    # Find most recent .jsonl file matching project
    project_pattern = project_dir.replace("/", "-")
    session_files = list(claude_dir.glob(f"{project_pattern}/*.jsonl"))

    if not session_files:
        return None

    # Return most recently modified (active session)
    session_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(session_files[0])
```

**Extract Session ID from File:**

```python
# Read first message with sessionId field
with open(session_file) as f:
    for line in f:
        msg = json.loads(line)
        if msg.get("sessionId"):
            return msg["sessionId"]
```

### 2. Store in Database

Add column to `sessions` table:

```sql
ALTER TABLE sessions ADD COLUMN claude_session_file TEXT;
```

Update session when Claude detected:

```python
# In output_poller.py
if current_command == "claude":
    session_file = find_claude_session_file(session.working_directory)
    if session_file:
        await db.update_session(
            session_id,
            claude_session_file=session_file
        )
        logger.info("Captured Claude session file: %s", session_file)
```

### 3. Stop Writing to Output File

**In `output_poller.py`:**

```python
# Check if Claude session file captured
session = await db.get_session(session_id)
use_native_logging = bool(session.claude_session_file)

if output_changed and not use_native_logging:
    # Only write to file if NOT using native logging
    output_file.write_text(clean_output, encoding="utf-8")
```

**Still yield OutputChanged events** (live Telegram updates):
```python
# Always yield for live view (Telegram editing)
yield OutputChanged(
    session_id=session_id,
    output=clean_output,
    started_at=started_at,
    last_changed_at=last_output_changed_at,
)
```

### 4. ETL: Convert .jsonl → Markdown

**Message Types:**

```python
# type: "user" - User message
{
  "type": "user",
  "message": {"role": "user", "content": "text here"},
  "timestamp": "2025-11-11T04:25:33.890Z"
}

# type: "assistant" - Claude response (with content blocks)
{
  "type": "assistant",
  "message": {
    "role": "assistant",
    "content": [
      {"type": "text", "text": "response here"},
      {"type": "tool_use", "name": "TodoWrite", "input": {...}},
      {"type": "text", "text": "more response"}
    ]
  },
  "timestamp": "..."
}

# type: "tool_result" - Tool execution result
{
  "type": "tool_result",
  "tool_use_id": "toolu_xxx",
  "content": "result text",
  "is_error": false
}
```

**Conversion Function:**

```python
def convert_claude_session_to_markdown(jsonl_path: str) -> str:
    """Convert Claude .jsonl session to readable Markdown.

    Args:
        jsonl_path: Path to .jsonl file

    Returns:
        Markdown formatted conversation
    """
    lines = Path(jsonl_path).read_text().strip().split("\n")

    # Extract metadata from first message
    first_msg = json.loads(lines[0])
    session_id = first_msg.get("sessionId", "unknown")

    md = f"# Claude Code Session\n\n"
    md += f"**Session ID**: {session_id}\n\n"
    md += "---\n\n"

    message_num = 1
    tool_use_map = {}  # Map tool_use_id → tool info

    for line in lines:
        msg = json.loads(line)
        msg_type = msg.get("type")
        timestamp = msg.get("timestamp", "")[:19]  # YYYY-MM-DDTHH:MM:SS

        if msg_type == "user":
            content = msg["message"]["content"]
            md += f"## Message {message_num} ({timestamp})\n\n"
            md += f"**User**: {content}\n\n"
            message_num += 1

        elif msg_type == "assistant":
            md += f"**Claude**:\n\n"

            for block in msg["message"]["content"]:
                if block["type"] == "text":
                    md += f"{block['text']}\n\n"

                elif block["type"] == "tool_use":
                    tool_name = block["name"]
                    tool_input = json.dumps(block["input"], indent=2)
                    tool_id = block["id"]

                    # Store for result matching
                    tool_use_map[tool_id] = tool_name

                    md += f"**Tool: {tool_name}**\n```json\n{tool_input}\n```\n\n"

        elif msg_type == "tool_result":
            tool_id = msg.get("tool_use_id", "")
            tool_name = tool_use_map.get(tool_id, "Unknown")
            content = msg.get("content", "")
            is_error = msg.get("is_error", False)

            status = "❌ Error" if is_error else "✓ Result"
            md += f"**{status}: {tool_name}**\n```\n{content}\n```\n\n"

    md += "---\n\n*Generated by TeleClaude*\n"
    return md
```

### 5. Download Handler Integration

**In `telegram_adapter.py` download callback:**

```python
async def _handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... existing code ...

    if data.startswith("download_full:"):
        session_id = data.split(":")[1]
        session = await db.get_session(session_id)

        # Check for native Claude session file FIRST
        if session.claude_session_file and Path(session.claude_session_file).exists():
            # ETL: Convert .jsonl → Markdown
            markdown = convert_claude_session_to_markdown(session.claude_session_file)

            # Write to temp file
            temp_file = Path(f"/tmp/claude_session_{session_id}.md")
            temp_file.write_text(markdown, encoding="utf-8")

            # Send to user
            await query.message.reply_document(
                document=open(temp_file, "rb"),
                caption=f"Claude session: {session.title}",
                filename=f"claude_session_{session_id[:8]}.md"
            )

            # Cleanup
            temp_file.unlink()

        else:
            # Fallback: Use tmux capture (old behavior)
            output_file = self._get_output_file_path(session_id)
            # ... existing code ...
```

## Implementation Steps

1. **Add database column** - `claude_session_file TEXT`
2. **Add detection function** - `find_claude_session_file()` in `output_poller.py`
3. **Update polling** - Detect Claude, extract session file, store in DB
4. **Stop file writes** - Skip when `claude_session_file` exists
5. **Add ETL function** - `convert_claude_session_to_markdown()` in new module
6. **Update download handler** - Prefer native logs over tmux capture

## Benefits

✅ **10x smaller files** - 516KB → 50KB (structured conversation only)
✅ **Readable format** - Markdown with clear user/assistant/tool flow
✅ **No duplication** - No TUI redraws, just real conversation
✅ **Searchable** - Easy to grep/parse Markdown
✅ **No hooks required** - Uses Claude's native session files
✅ **Automatic** - Works for all Claude sessions, no setup

## Edge Cases

1. **Claude session not found** - Fallback to tmux capture
2. **Claude exits mid-session** - Session file still exists, download works
3. **Non-Claude sessions** - Use tmux capture (vim, htop, etc.)
4. **Old sessions** - No `claude_session_file` → fallback to tmux

## Testing

```bash
# 1. Start Claude Code session
claude

# 2. Check session file captured
sqlite3 teleclaude.db "SELECT claude_session_file FROM sessions WHERE session_id = 'xxx'"

# 3. Work in session (tools, commands, etc.)

# 4. Click download button in Telegram

# 5. Verify:
#    - Received .md file (not .txt)
#    - File is readable Markdown
#    - Contains conversation (user + assistant + tools)
#    - No TUI noise
```

---

**Next:** Implement in this order → DB migration → Detection → ETL → Download handler
