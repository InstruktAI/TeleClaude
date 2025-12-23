# Send Result Tool - Requirements

## Problem Statement

AI agents running in TeleClaude sessions can only communicate results through the streaming terminal output message. This message:
- Gets edited in-place every 1 second
- Is truncated to ~3400 characters
- Has status footer (running time, size, download link)
- Is unsuitable for presenting clean, formatted results

Users expect clean presentation of:
- Markdown tables
- Analysis reports
- Structured data
- Code blocks with syntax highlighting

## Goals (Must Have)

### 1. New MCP Tool: `teleclaude__send_result`

**Parameters:**
- `content: str` (required) - Markdown-formatted content to display

**Auto-injected:**
- `session_id` from `TELECLAUDE_SESSION_ID` environment variable (already wired in mcp-wrapper.py)

**Returns:**
- Success: `{"status": "success", "message_id": "..."}`
- Error: `{"status": "error", "message": "..."}`

### 2. Message Formatting

**Input processing:**
1. Strip outer triple-backtick wrapper if present (AI often wraps output in code blocks)
2. Preserve inner formatting (tables, code blocks, lists)

**Output formatting:**
1. Use Telegram's MarkdownV2 parse mode
2. Escape special characters as required by MarkdownV2 spec
3. Send as new message (NOT edit existing output message)

### 3. Message Lifecycle

- Messages persist until session is closed
- NOT tracked in `pending_feedback_deletions` (unlike ephemeral feedback)
- NOT auto-deleted on next user input (unlike pending_deletions)
- Cleaned up when session closes (same as other session resources)

### 4. Tool Description (for AI triggering)

The tool description must guide AI agents on when to use it:

```
Send formatted results to the user as a separate message (not in the streaming terminal output).

Use this tool when:
- User asks for analysis, reports, or structured output
- You have results to present (tables, lists, summaries)
- User explicitly asks to "show results" or "display findings"
- Output would be cleaner as a standalone message vs terminal stream

Content MUST be valid Markdown. Examples:
- Tables: | Col1 | Col2 |\n|------|------|\n| val1 | val2 |
- Code blocks: ```python\ncode here\n```
- Lists, headers, bold/italic text

The message appears as a separate chat message, persists until session ends,
and renders with full Markdown formatting.
```

## Non-Goals (Out of Scope)

- File attachments (already handled by `teleclaude__send_file`)
- Interactive elements (buttons, inline keyboards)
- Message editing/updating after send
- Sending to other sessions (use existing `teleclaude__send_message` for that)
- HTML formatting (Markdown only)

## Technical Constraints

### MarkdownV2 Escaping

Telegram's MarkdownV2 requires escaping these characters outside code blocks:
```
_ * [ ] ( ) ~ ` > # + - = | { } . !
```

Must implement proper escaping that:
- Preserves intentional formatting (bold, italic, code)
- Escapes literal special characters
- Handles nested code blocks correctly

### Existing Primitives to Use

- `AdapterClient.send_message()` - sends to origin adapter
- `MessageMetadata(parse_mode="MarkdownV2")` - sets Telegram parse mode
- `db.get_session(session_id)` - retrieves session for adapter routing
- `TELECLAUDE_SESSION_ID` injection - already handled by mcp-wrapper.py

## Edge Cases

1. **Empty content** - Return error, don't send empty message
2. **Very long content** - Telegram limit is 4096 chars; truncate with indicator if exceeded
3. **Invalid markdown** - Send as plain text fallback if MarkdownV2 parsing fails
4. **Session not found** - Return clear error message
5. **Non-UI adapter origin** - If session origin is Redis (AI-to-AI), skip send or send to first UI observer

## Success Criteria

1. AI can call `teleclaude__send_result` with markdown content
2. Content appears as separate Telegram message in session topic
3. Tables, code blocks, lists render correctly with MarkdownV2
4. Messages persist until session closes
5. Tool description effectively triggers AI usage for result presentation
