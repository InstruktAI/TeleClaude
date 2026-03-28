# os-managed-todo-watchers — Demo

## Medium

CLI + service verification. The demo validates the full pipeline: path filtering, daemon
route, watcher process behavior, service installation, and old-watcher removal.

## What the User Observes

### 1. Path filtering works correctly

```bash
# Run the filter test suite — all xfail markers removed, all tests GREEN
uv run pytest tests/unit/services/test_todo_watcher_filter.py -v
```

Expected: 48+ tests pass covering normalization, noise rejection, allowlist accept/reject,
directory events, move events, and boundary cases.

### 2. Daemon route accepts authenticated watcher notifications

```bash
# Run the route test suite — auth, trust, re-filtering, digest-gated emission
uv run pytest tests/unit/api/test_todo_watcher_route.py -v
```

Expected: All route tests pass. Invalid/missing secrets rejected. Untrusted projects
rejected. Non-matching paths stripped server-side. Digest-unchanged notifications
suppress emission.

### 3. Watcher process batches and delivers notifications

```bash
# Run the process test suite — observation scope, batching, no semantic processing
uv run pytest tests/unit/services/test_todo_watcher_process.py -v
```

Expected: Multiple events within debounce window coalesce into one notification.
Duplicate paths deduplicated. Notification payload contains only `project_root` and
`changed_paths`.

### 4. Service installation works on current platform

```bash
# Run the installation test suite — secrets, launchd/systemd, idempotency
uv run pytest tests/unit/project_setup/test_todo_watcher_install.py -v
```

Expected: Secret generated with sufficient entropy. Unique per project. Injected into
service environment. Platform-appropriate service file created. No WatchPaths or
systemd.path unit. Idempotent reinstall.

### 5. Old in-process watcher is removed

```bash
# Run the removal verification suite — AST-based checks on daemon.py
uv run pytest tests/unit/core/test_todo_watcher_removal.py -v
```

Expected: `daemon.py` has no TodoWatcher reference. `teleclaude/core/todo_watcher.py`
has no TodoWatcher class, no \_TodoHandler class, no watchdog import.

### 6. `telec init` advertises the new watcher service

```bash
# Verify the user-facing init help text mentions todo watcher installation
uv run telec init -h
```

Expected: Help output says `telec init` installs docs sync and todo watcher services.

### 7. Full test suite stays green

```bash
# Run all tests to confirm no regressions
make test
```

Expected: All tests pass. No import errors from removed module. No broken references.

### 8. Live service verification (manual, post-deployment)

After running `telec init` on a project:

```bash
# macOS: verify launchd agent is loaded
launchctl list | grep teleclaude.todo

# Linux: verify systemd service is active
systemctl --user status teleclaude-todo-*

# Touch a todo file and check daemon logs for notification receipt
touch todos/roadmap.yaml
# Daemon log should show watcher notification received and processed
```
