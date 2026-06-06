## Build Gates (Builder)

- [x] Task 1: Add the unified typed remote-dispatch primitive
- [x] Task 2: Add the session-ownership resolver
- [x] Task 3: Migrate the `_session.py` close-forward path and remove `forward_command`
- [x] Task 4: Migrate `session_remote.py` close path onto the primitive
- [x] Task 5: Address carried-over remote-close authorization, completion-event, and API-boundary findings

### Verification

- `uv run pytest tests/agent_runtime/test_session_lifecycle.py`: PASS (`24 passed`, `5 snapshots passed`)
- `uv run ruff check teleclaude/core/adapter_client/_remote.py teleclaude/api/session_ownership.py teleclaude/core/command_handlers/_session.py teleclaude/api/session_remote.py teleclaude/api/sessions_routes.py tests/agent_runtime/test_session_lifecycle.py`: PASS
- `telec code test`: PASS
- `telec code lint`: PASS
- `rg -n "forward_command" teleclaude tests`: no matches

### User-Facing Verification

- Path: `DELETE /sessions/{id}?computer=<peer>` exercised through `tests/agent_runtime/test_session_lifecycle.py::test_delete_remote_session_forwards_to_cached_owner_and_returns_completion_event`.
- Observed result: the route accepts a cached peer-owned remote close with HTTP 202, returns the close `completion_event`, and dispatches to the cached owning computer without requiring a local DB row.
