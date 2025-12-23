# Send Result Tool - Implementation Plan

## Groups 1-4: Build Tasks (executed by /next-build)

### Group 1: Core Implementation

- [x] **PARALLEL** Add `teleclaude__send_result` tool definition to `teleclaude/mcp_server.py`:
  - Add Tool entry in `list_tools()` with description from requirements
  - Add handler in `call_tool()` that extracts content and calls implementation method
  - Add `teleclaude__send_result()` method that:
    1. Validates content is non-empty
    2. Gets session from `session_id` (injected from env)
    3. Strips outer backticks from content
    4. Calls `adapter_client.send_message()` with MarkdownV2 metadata
    5. Returns success/error response

- [x] **PARALLEL** Add MarkdownV2 escaping utility to `teleclaude/utils/markdown.py` (new file):
  - Function `escape_markdown_v2(text: str) -> str` that escapes special chars
  - Function `strip_outer_codeblock(text: str) -> str` that removes outer triple-backticks
  - Handle edge cases: preserve inner code blocks, escape outside them

### Group 2: Message Handling

- [x] **DEPENDS: Group 1** ~~Add `send_result` method to `TelegramAdapter`~~ (Not needed - implemented in MCP server using AdapterClient.send_message):
  - ~~Accept session and markdown content~~
  - ~~Apply MarkdownV2 escaping~~
  - ~~Handle Telegram 4096 char limit (truncate with indicator)~~
  - ~~Fallback to plain text if MarkdownV2 parsing fails~~
  - ~~Return message_id~~

- [x] **DEPENDS: Group 1** Update `bin/mcp-wrapper.py` TOOL_NAMES list:
  - Tool auto-discovered via grep pattern (no manual update needed)
  - Verified not in exclusion list

### Group 3: Testing

- [x] **DEPENDS: Group 2** Add unit tests in `tests/unit/test_markdown_utils.py`:
  - Test `escape_markdown_v2()` with various inputs
  - Test `strip_outer_codeblock()` preserves inner content
  - Test edge cases: empty string, no backticks, nested code blocks

- [x] **DEPENDS: Group 2** Add unit tests in `tests/unit/test_mcp_send_result.py`:
  - Test tool returns error for empty content
  - Test tool returns error for missing session
  - Test successful send returns message_id
  - Mock adapter_client.send_message

- [x] **DEPENDS: Group 2** Run full test suite: `make test`

### Group 4: Documentation & Polish

- [x] **DEPENDS: Group 3** Update `docs/mcp-architecture.md`:
  - Add `teleclaude__send_result` to the list of public tools
  - Add brief description

- [x] **DEPENDS: Group 3** Final lint/format check: `make lint && make format`

## Groups 5-6: Review & Finalize (handled by other commands)

### Group 5: Review

- [ ] **SEQUENTIAL** Review created (-> /next-review)
- [ ] **SEQUENTIAL** Review feedback handled

### Group 6: Merge & Deploy

- [ ] **SEQUENTIAL** Tests pass locally
- [ ] **SEQUENTIAL** Merged to main and pushed
- [ ] **SEQUENTIAL** Deployment verified
- [ ] **SEQUENTIAL** Roadmap item marked complete

## Implementation Notes

### Tool Definition Pattern

Follow existing tool patterns in `mcp_server.py`:
```python
Tool(
    name="teleclaude__send_result",
    title="TeleClaude: Send Result",
    description="...",  # From requirements
    inputSchema={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Markdown-formatted content to display",
            },
        },
        "required": ["content"],
    },
),
```

### MarkdownV2 Characters to Escape

```python
MARKDOWN_V2_SPECIAL = r'_*[]()~`>#+-=|{}.!'
```

Must NOT escape inside code blocks (`` ` `` or ``` ``` ```).

### Outer Codeblock Stripping

Pattern to match and strip:
```python
OUTER_CODEBLOCK = re.compile(r'^```\w*\n(.*)\n```$', re.DOTALL)
```

### Message Limit Handling

Telegram limit: 4096 characters. If exceeded:
```python
if len(formatted) > 4096:
    formatted = formatted[:4090] + "\n..."
```
