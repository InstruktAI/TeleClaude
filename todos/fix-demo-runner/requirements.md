# Requirements: fix-demo-runner

## Goal

Fix two bugs preventing the demo runner from working end-to-end:

1. Existing demo snapshots lack the `demo` field required by the CLI runner.
2. `render_widget`, `send_result`, and `send_file` force the AI to provide `session_id` manually, but the MCP wrapper already knows the caller's session. Extend the wrapper's auto-injection (same pattern as `cwd`) to cover `session_id`.

## Scope

### In scope

- Add `demo` shell command field to `demos/themed-primary-color/snapshot.json`
- Add `demo` shell command field to `demos/tui-markdown-editor/snapshot.json`
- Extend MCP wrapper auto-injection to populate `session_id` from the session marker when not explicitly provided (same mechanism as `cwd` and `caller_session_id`)
- Remove `session_id` from `required` in tool schemas for `render_widget`, `send_result`, `send_file`
- Clean up `/next-demo` command artifact — no session_id ceremony

### Out of scope

- Changes to the CLI runner's demo execution logic
- Handler-level changes (handlers receive `session_id` as before — the wrapper fills it in)
- Changes to `caller_session_id` injection

## Success Criteria

- [ ] `telec todo demo themed-primary-color` executes and exits 0
- [ ] `telec todo demo tui-markdown-editor` executes and exits 0
- [ ] AI calls `render_widget(data={...})` without `session_id` — wrapper injects it, widget renders
- [ ] AI calls `send_result(content="...")` without `session_id` — wrapper injects it, result sends
- [ ] AI calls `send_file(file_path="...")` without `session_id` — wrapper injects it, file sends
- [ ] Explicit `session_id` still works (e.g. orchestrator targeting a worker's session)

## Constraints

- Auto-injection uses the existing wrapper mechanism (`CONTEXT_TO_INJECT` / injection logic in `_inject_context`)
- No handler-level fallback logic — the wrapper provides `session_id` by contract
- Backward compatible: explicit `session_id` from the AI takes precedence

## Risks

- None. Extends an established pattern.
