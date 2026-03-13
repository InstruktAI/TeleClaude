# Implementation Plan: rlf-services

## Overview

Decompose two oversized service-layer files into focused submodules using `APIRouter` modules
(for api_server.py) and Python mixins (for daemon.py). No behavior changes; module size
guardrail (1000-line limit) satisfied for both target files.

## Phase 1: api_server.py decomposition

### Task 1.1: Extract stateless route modules

**File(s):** `teleclaude/api/agents_routes.py`, `teleclaude/api/people_routes.py`, `teleclaude/api/jobs_routes.py`

- [x] Create agents_routes.py with `/agents` endpoints
- [x] Create people_routes.py with `/people` endpoints
- [x] Create jobs_routes.py with `/jobs` endpoints

### Task 1.2: Extract stateful route modules

**File(s):** `teleclaude/api/settings_routes.py`, `teleclaude/api/chiptunes_routes.py`, `teleclaude/api/computers_routes.py`, `teleclaude/api/projects_routes.py`, `teleclaude/api/notifications_routes.py`

- [x] Create each module with module-level singleton state and `configure()` setter
- [x] Wire configure() calls from APIServer.__init__ and property setters

### Task 1.3: Extract sessions route modules

**File(s):** `teleclaude/api/sessions_routes.py`, `teleclaude/api/sessions_actions_routes.py`

- [x] Create sessions_routes.py with core CRUD routes (list, create, delete, send-message)
- [x] Create sessions_actions_routes.py with action routes (keys, voice, file, restart, revive, messages, run, unsubscribe, result, widget, escalate)

### Task 1.4: Extract WebSocket mixin

**File(s):** `teleclaude/api/ws_mixin.py`, `teleclaude/api/ws_constants.py`

- [x] Create ws_constants.py with WS constants and _WsClientState
- [x] Create ws_mixin.py with _WebSocketMixin containing all WS support methods
- [x] APIServer inherits from _WebSocketMixin

### Task 1.5: Rewrite api_server.py

**File(s):** `teleclaude/api_server.py`

- [x] Replace inline route closures with include_router() calls
- [x] Add configure() calls for stateful modules in __init__ and property setters
- [x] Add _event_db property with setter that propagates to notifications_routes
- [x] Extend cache.setter to propagate to sessions/computers/projects route modules
- [x] Remove all inline WebSocket methods (now in ws_mixin.py)
- [x] Result: 906 lines (under 1000)

---

## Phase 2: daemon.py decomposition

### Task 2.1: Extract hook outbox mixin

**File(s):** `teleclaude/daemon_hook_outbox.py`

- [x] Create _DaemonHookOutboxMixin with all hook outbox methods
- [x] Move _HookOutboxQueueItem, _HookOutboxSessionQueue dataclasses and HOOK_OUTBOX_* constants
- [x] TYPE_CHECKING declarations for self.* attributes used by mixin methods

### Task 2.2: Extract session/event-handler mixin

**File(s):** `teleclaude/daemon_session.py`

- [x] Create _DaemonSessionMixin with session lifecycle handlers and output-wait helpers
- [x] Move OutputChangeSummary dataclass and AGENT_START_* constants
- [x] TYPE_CHECKING declarations for self.* attributes used by mixin methods

### Task 2.3: Extract event platform mixin

**File(s):** `teleclaude/daemon_event_platform.py`

- [x] Create _DaemonEventPlatformMixin with _start_event_platform, _init_webhook_service, _deployment_fanout_consumer, _contract_sweep_loop
- [x] TYPE_CHECKING declarations for self.* attributes used by mixin methods

### Task 2.4: Update daemon.py

**File(s):** `teleclaude/daemon.py`

- [x] TeleClaudeDaemon inherits from all three mixins
- [x] Remove all extracted methods and module-level items
- [x] Result: 859 lines (under 1000)

---

## Phase 3: Validation

### Task 3.1: Tests

- [x] Run `make test` — 139/139 passing

### Task 3.2: Quality Checks

- [x] Add new files to pyproject.toml per-file-ignores for C901 (existing complexity transferred from exempt files)
- [x] Run `ruff check --fix` on all changed files — clean
- [x] Lint note: `make lint` still fails due to 19 pre-existing oversized files not in task scope (see deferrals.md)
- [x] Verify no unchecked implementation tasks remain

---

## Phase 4: Review Readiness

- [x] Requirements reflected in code changes (api_server.py 906 lines, daemon.py 859 lines)
- [x] All implementation tasks marked [x]
- [x] Deferrals documented in deferrals.md
