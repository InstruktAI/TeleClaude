# Implementation Plan: deployment-channels

## Overview

Channel-based deployment using the hooks framework. A webhook handler receives
GitHub events via the inbound infrastructure, checks channel config, and executes
updates. Redis fan-out via EventBusBridge ensures all daemons respond.

---

## Phase 1: Core Changes

### Task 1.1: Channel config schema

**File(s):** `teleclaude/config/schema.py`

- [x] Add `DeploymentConfig` Pydantic model:
  ```python
  class DeploymentConfig(BaseModel):
      channel: Literal["alpha", "beta", "stable"] = "alpha"
      pinned_minor: str = ""
  ```
- [x] Add validator: `pinned_minor` required and non-empty when `channel=stable`
- [x] Add `deployment: DeploymentConfig = DeploymentConfig()` to `ProjectConfig`

### Task 1.2: Deployment webhook handler

**File(s):** `teleclaude/deployment/__init__.py`, `teleclaude/deployment/handler.py`

- [x] Create `teleclaude/deployment/` package with `__init__.py`
- [x] Create async handler: `async def handle_deployment_event(event: HookEvent) -> None`
- [x] Read channel config via `load_project_config()`
- [x] Decision logic based on event properties:
  - Alpha: `event.type == "push"` and `ref == "refs/heads/main"` → update
  - Beta: `event.type == "release"` and `action == "published"` → update
  - Stable: same as beta but version within pinned minor → update
  - Otherwise → skip (log at debug level)
- [x] Fan-out: if `event.source == "github"` (direct webhook), publish
      `HookEvent.now(source="deployment", type="version_available", ...)`
      to internal event bus for Redis broadcast to other daemons
- [x] If `event.source == "deployment"` (Redis fan-out), only execute locally

### Task 1.3: Contract and handler registration at daemon startup

**File(s):** `teleclaude/daemon.py` (in `_init_webhook_service()`)

- [x] Register handler: `handler_registry.register("deployment_update", handle_deployment_event)`
- [x] Register GitHub contract:
  ```python
  Contract(
      id="deployment-github",
      source_criterion=PropertyCriterion(match="github"),
      type_criterion=PropertyCriterion(match=["push", "release"]),
      target=Target(handler="deployment_update"),
      source="programmatic",
  )
  ```
- [x] Register fan-out contract:
  ```python
  Contract(
      id="deployment-fanout",
      source_criterion=PropertyCriterion(match="deployment"),
      type_criterion=PropertyCriterion(match="version_available"),
      target=Target(handler="deployment_update"),
      source="programmatic",
  )
  ```

### Task 1.4: Update executor

**File(s):** `teleclaude/deployment/executor.py`

- [x] `async def execute_update(channel: str, version_info: dict) -> None`
- [x] Sequence:
  1. Log update start, set Redis status `"updating"`
  2. Alpha: `git pull --ff-only origin main`
  3. Beta/Stable: `git fetch --tags && git checkout v{version}`
  4. Set Redis status `"migrating"`, run `migration_runner.run_migrations()`
  5. Set Redis status `"installing"`, run `make install` (60s timeout)
  6. Set Redis status `"restarting"`, trigger `os._exit(42)`
- [x] On failure: log error, set Redis status `"update_failed"`, do NOT restart
- [x] Redis key: `system_status:{computer_name}:deploy` (matches deploy_service.py)

### Task 1.5: Update `telec version`

**File(s):** `teleclaude/cli/telec.py` (version handler)

- [x] Load `ProjectConfig` via `load_project_config()` for `deployment.channel`
- [x] Replace hardcoded "alpha" with actual channel
- [x] Stable channel: also display pinned minor

---

## Phase 2: Validation

### Task 2.1: Tests

- [x] Unit test: config validation (valid channels, stable requires pinned_minor)
- [x] Unit test: handler decision logic per channel × event type
- [x] Unit test: handler skips irrelevant events
- [x] Unit test: executor alpha path (mock git + make install)
- [x] Unit test: executor beta/stable path (mock git fetch + checkout)
- [x] Unit test: migration failure halts update
- [x] Unit test: fan-out published for github source, not for deployment source
- [x] Integration test: HookEvent → handler → executor flow (covered by handler tests)
- [x] Run `make test`

### Task 2.2: Quality Checks

- [x] Run `make lint`

---

## Phase 3: Review Readiness

- [x] Confirm requirements reflected in code
- [x] All tasks marked `[x]`
