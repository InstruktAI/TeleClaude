# DOR Report: fix-demo-runner

## Draft Assessment

**Score:** 8/10 (draft — pending formal gate)
**Assessed:** 2026-02-22

## Summary

Both bugs confirmed. Bug 1 is trivial (add JSON fields). Bug 2 is an extension of the existing MCP wrapper injection pattern — `cwd` and `caller_session_id` are already auto-injected; `session_id` needs the same treatment. No handler changes, no fallback logic, no AI awareness of infrastructure.

## Gate Analysis

| #   | Gate               | Draft Result | Detail                                                                                              |
| --- | ------------------ | ------------ | --------------------------------------------------------------------------------------------------- |
| 1   | Intent & success   | PASS         | Both bugs documented with root cause. 6 success criteria.                                           |
| 2   | Scope & size       | PASS         | 2 JSON edits + 1 wrapper change + 1 tool_definitions change + 1 command artifact. Fits one session. |
| 3   | Verification       | PASS         | CLI exit codes for demos, widget rendering without explicit session_id, backward compat.            |
| 4   | Approach known     | PASS         | Extends established injection pattern in `mcp_wrapper.py`.                                          |
| 5   | Research           | N/A          | No third-party dependencies.                                                                        |
| 6   | Dependencies       | PASS         | `demo-runner` functionally delivered.                                                               |
| 7   | Integration safety | PASS         | Additive — explicit `session_id` still takes precedence.                                            |
| 8   | Tooling impact     | N/A          | No tooling changes.                                                                                 |

## Confirmed Against Codebase

- `demos/themed-primary-color/snapshot.json` — missing `demo` field
- `demos/tui-markdown-editor/snapshot.json` — missing `demo` field
- `teleclaude/entrypoints/mcp_wrapper.py:54-56` — `CONTEXT_TO_INJECT` maps `cwd` and `caller_session_id` for auto-injection; `session_id` not covered
- `teleclaude/entrypoints/mcp_wrapper.py:486-492` — `caller_session_id` injected from session marker; same source needed for `session_id`
- `teleclaude/mcp/tool_definitions.py:957` — `session_id` in `required` for `render_widget`

## Open Questions

None.
