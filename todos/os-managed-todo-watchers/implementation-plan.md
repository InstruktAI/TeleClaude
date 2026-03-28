# os-managed-todo-watchers — Implementation Plan

## Overview

Replace the daemon's in-process `TodoWatcher` (watchdog/FSEvents threads) with OS-managed
watcher services that report path changes to the daemon over its existing Unix-socket API.
Follows the additive-before-removal rollout sequence (R6.1): all replacement infrastructure
is live and verified before the old code path is removed.

The work is atomic — the pieces form one coherent behavior and are not independently
valuable. Estimated ~500 lines of new code across 4 modules, plus integration glue and
removal of the old watcher.

## Task Sequence

### [x] Task 1 — Path Filtering Module

**What:** Create `teleclaude/services/todo_watcher.py` with the pure filtering functions
required by both the watcher process (R1) and the daemon route (R2.3):

- `normalize_path(project_root, absolute_path) -> str` — project-relative POSIX
  normalization (R1.2).
- `is_path_allowed(path) -> bool` — R1.5 file pattern allowlist. Encodes the patterns:
  `todos/*.yaml`, `todos/*/*.md`, `todos/*/*.yaml`, `todos/_icebox/icebox.yaml`,
  `todos/_icebox/*/*.md`, `todos/_icebox/*/*.yaml`, `trees/*/todos/*/*.md`,
  `trees/*/todos/*/*.yaml`. Noise filtering (R1.4) runs before pattern matching —
  hidden files/directories and editor artifacts (`.swp`, `.bak`, `.tmp`, `~`-suffixed,
  hidden-prefixed) are rejected.
- `is_dir_event_allowed(path) -> bool` — R1.5 directory event patterns:
  `todos/<slug>`, `todos/_icebox/<slug>`, `trees/<slug>`, `trees/<slug>/todos/<slug>`.
- `evaluate_move_event(src, dst) -> list[str]` — evaluates both source and destination
  against the allowlist, returns matching paths (R1.3).
- `build_notification_payload(project_root, changed_paths) -> dict` — constructs the
  notification body containing only `project_root` and `changed_paths` (R1.7).

**Why:** The path filter is the shared contract between watcher and daemon. Implementing
it first establishes the data shape downstream tasks depend on. It is also the largest
test spec surface (48+ tests covering R1.2-R1.5), so making these GREEN early de-risks
the build.

**Verification:**

- Remove xfail markers from `tests/unit/services/test_todo_watcher_filter.py` — all
  `TestPathNormalization`, `TestMoveEventHandling`, `TestNoiseFiltering`,
  `TestFilePatternAllowlist`, `TestDirectoryEventAllowlist`, and `TestAllowlistBoundaries`
  tests pass.
- `test_todo_watcher_process.py::TestNoSemanticProcessing::test_notification_payload_contains_only_paths`
  passes (payload shape check).
- `test_todo_watcher_process.py::TestNoSemanticProcessing::test_watcher_does_not_import_cache_or_snapshot_modules`
  passes (dependency isolation check).

**Files:**

- Create: `teleclaude/services/todo_watcher.py`

---

### [x] Task 2 — Daemon Internal Route

**What:** Create `teleclaude/api/todo_watcher_routes.py` exposing a POST handler on the
internal (Unix-socket) router:

1. Extract `X-Watcher-Secret` header and validate against the stored secret (R2.1, R3.4).
   Implement as `_get_watcher_secret() -> str` that reads the persisted secret.
2. Parse JSON body: `{project_root, changed_paths}`.
3. Verify `project_root` belongs to a trusted directory via `_get_trusted_dirs()` wrapping
   `config.computer.get_all_trusted_dirs()` (R2.2).
4. Re-apply `is_path_allowed` + `is_dir_event_allowed` from the filter module server-side
   against `changed_paths` (R2.3). If all paths filter out, return 200 with no further
   processing.
5. If re-filtered paths affect stale-preparation logic, call
   `invalidate_stale_preparations(project_root, changed_paths)` from
   `teleclaude.core.next_machine.prepare_events` via `_invalidate_stale_preparations()`
   wrapper (R2.4).
6. Recompute the todo snapshot exactly once via `_recompute_todos()` wrapping
   `cache.refresh_local_todos(computer, project_root, "todo_updated")` (R2.5).
7. Compare the new snapshot digest against the previous via
   `_apply_snapshot_with_digest_check()` (R2.6). If changed, call `_emit_change_event()`
   to trigger cache/WebSocket fan-out.
8. Return 200 on success, 401/403 on missing/invalid secret (rejection must not leak
   the valid secret value — R3.4), 403/422 on untrusted project.

Follow the established route module pattern: module-level `_STATE` namespace,
`configure(cache: DaemonCache)` function, `router = APIRouter()`.

Register the router in `teleclaude/api_server.py`: import the route module, call
`configure(cache=cache)`, and `include_router`.

**Why:** The daemon route must be functional before the watcher process or service
installer exist (R6.1 — additive before removal). Building it after the filter module
means `is_path_allowed` / `is_dir_event_allowed` are already available for server-side
re-filtering. The route is independently testable with mock requests.

**Note (O1):** The test specs use specific mock target names (`_get_watcher_secret`,
`_recompute_todos`, `_invalidate_stale_preparations`, `_apply_snapshot_with_digest_check`,
`_emit_change_event`). Use these as internal function names in the route module, or adjust
the mock target paths in the test helpers to match the actual decomposition while preserving
all behavioral assertions.

The R2.3 test (`test_non_matching_paths_stripped_server_side`) asserts that only re-filtered
paths are passed to `_recompute_todos`. The test helper extracts `changed_paths` from the
mock call via positional arg inspection. Therefore `_recompute_todos` must accept
`(project_root, changed_paths)` as its signature — the filtered paths are passed in so the
test can verify server-side stripping worked. The internal implementation uses `project_root`
for the actual `cache.refresh_local_todos` call.

The handler function must be named `handle_watcher_notification` and defined at module level
(the test imports it directly: `from teleclaude.api.todo_watcher_routes import
handle_watcher_notification`).

**Verification:**

- Remove xfail markers from `tests/unit/api/test_todo_watcher_route.py` — all
  `TestWatcherRouteAuthentication`, `TestProjectTrustVerification`,
  `TestServerSideRefiltering`, `TestStalePreparationInvalidation`,
  `TestSingleRecomputation`, `TestDigestGatedEmission`, `TestTransport`, and
  `TestRolloutSafety` tests pass.
- Route is importable from `teleclaude.api.todo_watcher_routes` and has a `router` attribute.
- Route is reachable on the Unix-socket API (included in the FastAPI app).

**Files:**

- Create: `teleclaude/api/todo_watcher_routes.py`
- Modify: `teleclaude/api_server.py` (add import to the route bundle at lines 90-101,
  add `todo_watcher_routes.configure(cache=cache)` after line 108, add
  `self.app.include_router(todo_watcher_routes.router)` after line 118 — following
  the configure+include_router pattern established at lines 90-118)

---

### [x] Task 3 — Watcher Process

**What:** Add `TodoWatcherProcess` class to `teleclaude/services/todo_watcher.py` (same
module as the filter functions from Task 1):

- Constructor accepts `project_root: str` and optional `debounce_seconds: float = 1.0`.
  Exposes `project_root` and `recursive = True` attributes (R1.1).
- Uses watchdog `Observer` + `FileSystemEventHandler` to observe the project root
  recursively. Follows the pattern established in `teleclaude/cli/watch.py`.
- `handle_fs_event(path, event_type)` method: normalizes the path (R1.2), rejects noise
  (R1.4), checks allowlist for files (R1.5) or directory events, evaluates move events
  against both source and destination (R1.3). Matching paths are accumulated in the
  debounce buffer.
- After the debounce window expires, deduplicates accumulated paths and fires a single
  notification via the `on_notification` callback (R1.6).
- The notification payload contains only `project_root` and `changed_paths` (R1.7).
- Never imports `DaemonCache` or performs snapshot/digest/TUI work.

Add a CLI entry point for the watcher process. The OS service (launchd/systemd) invokes
this command. It:

- Reads `project_root` from arguments.
- Reads `TELECLAUDE_WATCHER_SECRET` from environment (injected by the service).
- Instantiates `TodoWatcherProcess`, sets `on_notification` to POST to the daemon's
  Unix socket endpoint (`/internal/watcher-notification`) with the secret in the
  `X-Watcher-Secret` header.
- Runs the observer loop until interrupted.

**Why:** The watcher process is the OS-managed replacement for the retired `TodoWatcher`.
It uses the filter functions from Task 1 and communicates with the route from Task 2.
Building it after both dependencies are in place allows end-to-end validation.

**Note (O3):** Test specs use `asyncio.sleep(2.0)` for debounce assertions. Make the
debounce window configurable via constructor parameter so tests can control timing, or
ensure the default window + sleep margin work together cleanly.

**Verification:**

- Remove xfail markers from `tests/unit/services/test_todo_watcher_process.py` — all
  `TestObservationScope`, `TestBatchingAndDebounce`, and `TestNoSemanticProcessing`
  tests pass.
- The module does not depend on `teleclaude.core.cache` (verified by existing
  `test_watcher_does_not_import_cache_or_snapshot_modules` spec).

**Files:**

- Modify: `teleclaude/services/todo_watcher.py` (add `TodoWatcherProcess` class)
- Create: CLI entry point (e.g., `teleclaude/cli/todo_watch.py` — builder determines
  exact placement following existing CLI patterns)

---

### [x] Task 4 — Service Installation and Secret Management

**What:** Create `teleclaude/project_setup/todo_watcher_install.py` with:

- `install_todo_watcher(project_root: Path) -> None` — main entry point.
- `get_watcher_secret(project_root: Path) -> str | None` — retrieve stored secret for
  daemon-side verification.
- **Secret generation (R3.1):** generate a cryptographically random secret (>=32 chars,
  e.g., `secrets.token_hex(32)`) per project. Each project gets a unique secret.
- **Secret storage (R3.2):** persist the secret so the daemon can verify incoming
  requests. The storage location is an implementation choice (e.g.,
  `~/.teleclaude/watcher-secrets/` keyed by project slug).
- **Secret injection (R3.3):** embed `TELECLAUDE_WATCHER_SECRET` as an environment
  variable in the generated launchd plist / systemd service file.
- **macOS (R4.1):** generate a launchd plist with `KeepAlive`, `RunAtLoad`, the watcher
  CLI command, and the secret env var. Use `launchctl bootout` + `bootstrap` for
  installation. Label: `ai.instrukt.teleclaude.todo.<project-slug>`. Follow the
  pattern in `teleclaude/project_setup/sync.py:_install_launchd_watch`.
- **Linux (R4.2):** generate a systemd `--user` service with `Restart=on-failure` policy,
  the watcher CLI command, and the secret env var. Use `systemctl --user daemon-reload` +
  `enable --now`. No `.path` unit.
- **No coarse path units (R4.3):** no `WatchPaths` in plist, no `systemd.path` unit.
- **Idempotent (R4.5):** re-running replaces cleanly (bootout old before bootstrap new
  on macOS; daemon-reload + enable on Linux).
- **One service per project (R4.6):** label/unit name includes the project slug.

Integrate into `teleclaude/project_setup/init_flow.py`: call
`install_todo_watcher(project_root)` after `install_docs_watch(project_root)`.

**Why:** Service installation is the deployment mechanism that makes the watcher
OS-managed. It depends on the CLI entry point from Task 3 (the plist/service must
reference the correct command). Building it after the process exists allows the installer
to reference the real command path.

**Note (O2):** Test specs read plist/service content from `~/Library/LaunchAgents` and
`~/.config/systemd/user`. The builder should structure the installer to accept an output
directory parameter (defaulting to the real OS path) or redirect output in test setup,
preserving all behavioral assertions about content.

**Verification:**

- Remove xfail markers from `tests/unit/project_setup/test_todo_watcher_install.py` —
  all `TestSecretGeneration`, `TestSecretStorage`, `TestSecretInjection`,
  `TestMacOSInstallation`, `TestLinuxInstallation`, `TestNoCoarsePathUnits`,
  `TestIdempotentInstallation`, and `TestOneServicePerProject` tests pass.

**Files:**

- Create: `teleclaude/project_setup/todo_watcher_install.py`
- Modify: `teleclaude/project_setup/init_flow.py` (add import + call after
  `install_docs_watch` at ~line 196)

---

### [x] Task 5 — Daemon TodoWatcher Removal

**What:** Remove the in-process `TodoWatcher` from the daemon:

1. Remove `from teleclaude.core.todo_watcher import TodoWatcher` import from
   `teleclaude/daemon.py` (line 36).
2. Remove the task creation block at lines 551-554:
   `todo_watcher = TodoWatcher(self.cache)`,
   `self.todo_watcher_task = asyncio.create_task(...)`,
   done callback, and log line.
3. Remove the shutdown entry `("todo_watcher_task", "Todo watcher task stopped")` from
   `stop()` (line 595).
4. Remove the `self.todo_watcher_task` instance variable declaration at line 254.
5. Delete `teleclaude/core/todo_watcher.py` entirely. The `TodoWatcher` class,
   `_TodoHandler` class, `_is_relevant` helper, `_classify_event` helper, and all
   `watchdog` imports are no longer needed.
6. Delete `tests/unit/core/test_todo_watcher.py` — characterization tests for the retired
   module that will break on import after the module is removed.

**Why:** This is the final step after all replacement infrastructure is functional
(R6.1 — additive before removal). The daemon no longer owns filesystem observation;
the OS-managed watcher service does. No fallback mechanism is retained (R5.1).

**Verification:**

- Remove xfail markers from `tests/unit/core/test_todo_watcher_removal.py` — all
  `TestNoDaemonFileObservation` and `TestInProcessWatcherRemoval` tests pass.
- `daemon.py` contains no reference to `TodoWatcher` or task named `"todo-watcher"`.
- `teleclaude/core/todo_watcher.py` either does not exist or contains no `TodoWatcher`/
  `_TodoHandler` classes and no `watchdog` imports.
- Pre-commit hooks pass (no dangling imports from removed module).

**Files:**

- Modify: `teleclaude/daemon.py` (remove import at line 36, task creation at lines
  551-554, shutdown entry at line 595)
- Delete: `teleclaude/core/todo_watcher.py`
- Delete: `tests/unit/core/test_todo_watcher.py`

---

### [x] Task 6 — CLI Help Text Update

**What:** Update the `telec init` CLI help text to mention todo watcher service
installation alongside the existing docs sync functionality (review-awareness note from
requirements).

**Why:** DoD gate 6 (Documentation) requires CLI help text updates for changed
subcommands. The `telec init` behavior now includes todo watcher installation — users
should see this reflected.

**Verification:**

- `telec init --help` output mentions todo watcher service installation.
- Pre-commit hooks pass.

**Files:**

- Modify: CLI surface definition for `telec init` (e.g.,
  `teleclaude/cli/telec/surface.py` or the function's docstring/help parameter)

---

## Rollout Sequence

```
Task 1 (filter) → Task 2 (route) → Task 3 (process) → Task 4 (install) → Task 5 (removal) → Task 6 (docs)
```

Each task is additive until Task 5. The replacement path is fully live and tested
before the old path is removed.

## Cross-Cutting Concerns

- **Secret storage location:** Builder chooses where to persist watcher secrets.
  Must be readable by both the installer (write) and the daemon route (read).
  A location under `~/.teleclaude/` keyed by project slug is the natural fit.
- **Existing old-watcher tests:** `tests/unit/core/test_todo_watcher.py` tests the
  retired module and must be removed in Task 5.
- **Test helper adjustments (O1-O3):** Mock targets and filesystem helpers in test
  specs may need adaptation to match actual implementation decomposition. All
  behavioral assertions must be preserved.
- **1:1 test mapping:** New source files need corresponding test files. The xfail
  spec files already cover this: `test_todo_watcher_filter.py` maps to the filter
  surface, `test_todo_watcher_process.py` to the process, `test_todo_watcher_route.py`
  to the route, `test_todo_watcher_install.py` to the installer,
  `test_todo_watcher_removal.py` to the removal verification.
