# Review Findings — os-managed-todo-watchers

## Scope

- No unresolved findings. The watcher endpoint now rejects TCP/loopback requests on the shared FastAPI app and remains usable on the Unix-socket path.

## Code

- No unresolved findings. Per-project watcher service identity now includes a stable path hash, and the Linux unit writes the already-quoted watcher command directly into `ExecStart`, preserving valid spaced paths.

## Paradigm

- No findings. The fixes stayed at the existing API boundary, watcher route boundary, and installer boundary; no new cross-layer abstractions or bypasses were introduced.

## Principles

- No findings. Boundary translation remains at the edge, service identity is derived from project identity rather than a shared basename, and the transport gate fails closed at the watcher route boundary.

## Security

- No unresolved findings. Session creation now rejects `human_role` overrides unless the authenticated caller is already admin, which closes the prior authorization bypass.

## Tests

- No unresolved findings. Route coverage now exercises the shared `APIServer` surface and asserts TCP requests are rejected with `403`, and installer tests now redirect launchd/systemd artifacts and watcher secrets into per-test temp homes.

## Errors

- No findings.

## Types

- No findings.

## Comments

- No findings.

## Logging

- No findings.

## Demo

- No unresolved findings. `uv run telec todo demo validate os-managed-todo-watchers` passed during re-review. Browser smoke verification is not applicable because this change does not affect a browser-rendered UI path.

## Docs

- No unresolved findings. `uv run telec init -h` still advertises docs sync and todo watcher services, matching the updated docs.

## Resolved Since Prior Review

- Security/Critical auth bypass in session creation was fixed in `6140f5b2b`.
- Scope/Important TCP exposure of `/internal/watcher-notification` and the shallow transport test were fixed in `584532cfe`.
- Code/Important per-project service label collisions were fixed in `c48e636b0`.
- Code/Important Linux `ExecStart` breakage for valid paths with spaces was fixed in `2b73b7fbe`.
- Tests/Important installer home-directory side effects were fixed in `4e425789c`.

## Why No Issues

- Paradigm fit verified: the fixes reuse the existing route/configure pattern, keep watcher semantics in the daemon path, and avoid new transport-specific leakage into core logic.
- Requirements re-checked: the remaining acceptance bar from the prior review was limited to role authority, Unix-socket-only watcher delivery, one-service-per-project identity, valid Linux watcher startup for spaced paths, and hermetic tests; each item is now pinned in code and tests.
- Copy-paste duplication checked: the new helper logic is localized and purpose-built rather than duplicating unrelated route or installer flows.
- Security reviewed: the prior `human_role` escalation path now fails closed, and the watcher route no longer accepts the TCP/public surface.

## Verification

- `uv run pytest tests/unit/api/test_sessions_routes.py tests/unit/api/test_todo_watcher_route.py tests/unit/project_setup/test_todo_watcher_install.py -q`
- `uv run ruff check teleclaude/api/sessions_routes.py teleclaude/api/todo_watcher_routes.py teleclaude/project_setup/todo_watcher_install.py tests/unit/api/test_sessions_routes.py tests/unit/api/test_todo_watcher_route.py tests/unit/project_setup/test_todo_watcher_install.py`
- `uv run mypy teleclaude/api/sessions_routes.py teleclaude/api/todo_watcher_routes.py teleclaude/project_setup/todo_watcher_install.py tests/unit/api/test_sessions_routes.py tests/unit/api/test_todo_watcher_route.py tests/unit/project_setup/test_todo_watcher_install.py`
- `uv run telec todo demo validate os-managed-todo-watchers`
- `uv run telec init -h`
- Live UDS probe: a minimal uvicorn+httpx Unix-socket round trip reported `scope["client"] == None`, matching the watcher transport guard.

## Verdict

- APPROVE
