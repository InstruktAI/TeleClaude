# Requirements: direct-conversation-flag

## Goal

Add a `direct` boolean parameter to `teleclaude__send_message` and `teleclaude__start_session` MCP tools. When `direct=true`, the tool skips listener registration (`_register_listener_if_present`), enabling clean peer-to-peer agent communication without automatic notification subscriptions.

This implements the tool-level support for the Agent Direct Conversation procedure (`docs/global/general/procedure/agent-direct-conversation.md`).

## Scope

### In scope:

- Add `direct: bool = False` parameter to `teleclaude__send_message` handler
- Add `direct: bool = False` parameter to `teleclaude__start_session` handler
- Guard all `_register_listener_if_present` calls with `if not direct:`
- Pass `direct` through the MCP server dispatch layer (`_handle_send_message`, `_handle_start_session`)
- Update `StartSessionArgs` model with `direct` field
- Update MCP tool schema descriptions to document the flag
- Tests covering both paths (default subscription, direct skip)

### Out of scope:

- Bidirectional agent-link infrastructure
- Changes to `run_agent_command` or `get_session_data`
- Changes to the notification/listener system itself
- UI changes

## Success Criteria

- [ ] `send_message(direct=true)` delivers message without creating a notification subscription
- [ ] `start_session(direct=true)` creates session without creating a notification subscription
- [ ] Default behavior (`direct` omitted or `false`) is unchanged — subscriptions created as before
- [ ] MCP tool descriptions document the `direct` parameter and its purpose
- [ ] Tests verify listener is skipped when `direct=true` and called when `direct=false`
- [ ] Full test suite passes (`make test`)
- [ ] Lint passes (`make lint`)

## Key Files

| File                         | What changes                                                                                                                                         |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `teleclaude/mcp/handlers.py` | `teleclaude__send_message` (L521), `teleclaude__start_session` (L297), all `_register_listener_if_present` call sites (L361, L530, L643, L701, L720) |
| `teleclaude/mcp_server.py`   | `_handle_send_message` (L443), `_handle_start_session` (L439), tool schema registration                                                              |
| `teleclaude/core/models.py`  | `StartSessionArgs` (L703)                                                                                                                            |

## Constraints

- Must not break existing notification behavior — `direct` defaults to `False`
- The flag name must be `direct` (matches the procedure documentation)

## Risks

- Call sites for `_register_listener_if_present` span both local and remote paths; all must be guarded consistently
