# Implementation Plan: inbound-hook-service

## Overview

Wire the existing `InboundEndpointRegistry` and `NormalizerRegistry` into the daemon, update the normalizer signature to include headers, create a GitHub normalizer, implement path derivation, and start the channel subscription worker. The approach reuses all existing infrastructure — no new architectural patterns are introduced.

## Phase 1: Normalizer Signature & GitHub Normalizer

### Task 1.1: Update normalizer type to accept headers

**File(s):** `teleclaude/hooks/inbound.py`

- [x] Change `Normalizer` type alias from `Callable[[dict], HookEvent]` to `Callable[[dict, dict], HookEvent]` (payload, headers)
- [x] Update `handle_post()` to extract headers as a plain dict from `request.headers` and pass to normalizer: `event = normalizer(payload, dict(request.headers))`

### Task 1.2: Create GitHub normalizer

**File(s):** `teleclaude/hooks/normalizers/__init__.py`, `teleclaude/hooks/normalizers/github.py`

- [x] Create `teleclaude/hooks/normalizers/` package with `__init__.py`
- [x] Implement `normalize_github(payload: dict, headers: dict) -> HookEvent`:
  - Read `X-GitHub-Event` header (lowercased key lookup) for event type; fall back to `"unknown"` if missing
  - Extract `properties`: `repo` from `payload.repository.full_name`, `sender` from `payload.sender.login`, `action` from `payload.action` (if present), `ref` from `payload.ref` (if present)
  - Return `HookEvent.now(source="github", type=event_type, properties=properties, payload=payload)`
  - Handle `ping` event: extract `zen` and `hook_id` into properties

### Task 1.3: Create normalizer registration helper

**File(s):** `teleclaude/hooks/normalizers/__init__.py`

- [x] Add `register_builtin_normalizers(registry: NormalizerRegistry) -> None` that registers the GitHub normalizer under key `"github"`
- [x] This function is the single entry point for all built-in normalizers — future normalizers (WhatsApp, etc.) are added here

## Phase 2: Wire Into Daemon

### Task 2.1: Wire InboundEndpointRegistry and NormalizerRegistry

**File(s):** `teleclaude/daemon.py` (within `_init_webhook_service`)

**Note:** The daemon's `Config` dataclass (in `teleclaude/config/__init__.py`) does not have a `hooks` field. The existing code at line 1554 (`getattr(config, "hooks", None)`) is dead — it always returns `None`. The `HooksConfig` lives on `ProjectConfig` in `teleclaude/config/schema.py`, loaded via `teleclaude/config/loader.py:load_project_config()`. The daemon currently never loads project config. This task must bridge that gap.

- [x] Load project config in `_init_webhook_service()`: use `load_project_config()` to load `teleclaude.yml` from the project root (same pattern as `teleclaude/cron/runner.py`)
- [x] Replace dead `getattr(config, "hooks", None)` with project config access: `project_cfg.hooks`
- [x] Import `NormalizerRegistry` and `InboundEndpointRegistry` from `teleclaude.hooks.inbound`
- [x] Import `register_builtin_normalizers` from `teleclaude.hooks.normalizers`
- [x] Create `normalizer_registry = NormalizerRegistry()`
- [x] Call `register_builtin_normalizers(normalizer_registry)`
- [x] Create `inbound_registry = InboundEndpointRegistry(app, normalizer_registry, dispatcher.dispatch)`
- [x] Pass `inbound_registry` to `load_hooks_config()`: `await load_hooks_config(project_cfg.hooks.model_dump(), contract_registry, inbound_registry)`

### Task 2.2: Implement path derivation in config loading

**File(s):** `teleclaude/hooks/config.py`

- [x] Update inbound endpoint loading: when `source_config.path` is not set, derive path as `/hooks/inbound/{source_name}`
- [x] Log the derived path for observability

### Task 2.3: Make InboundSourceConfig.path optional

**File(s):** `teleclaude/config/schema.py`

- [x] Change `InboundSourceConfig.path` from required `str` to `Optional[str] = None`
- [x] Change `InboundSourceConfig.normalizer` from required `str` to `Optional[str] = None` (defaults to source name in config loading)

### Task 2.4: Wire channel subscription worker

**File(s):** `teleclaude/daemon.py`

- [x] Using the project config loaded in Task 2.1, check if `project_cfg.channel_subscriptions` is non-empty
- [x] If yes, import and start `run_subscription_worker()` as a background task with Redis client, subscriptions list, and shutdown event
- [x] Add done callback for error logging consistent with other background tasks

## Phase 3: Validation

### Task 3.1: Unit tests for GitHub normalizer

**File(s):** `tests/unit/test_github_normalizer.py`

- [x] Test `push` event: correct source, type, properties extraction
- [x] Test `ping` event: correct type, zen + hook_id in properties
- [x] Test `pull_request` event with action field
- [x] Test missing `X-GitHub-Event` header: falls back to `"unknown"` type
- [x] Test minimal payload (missing optional fields like `sender`, `ref`): no crash, properties populated where available

### Task 3.2: Integration test for inbound endpoint flow

**File(s):** `tests/integration/test_inbound_webhook.py`

- [x] Test end-to-end: POST to `/hooks/inbound/github` with valid HMAC + GitHub push payload → verify HookEvent dispatched
- [x] Test HMAC verification failure → 401
- [x] Test invalid JSON → 400
- [x] Test normalizer error → 400
- [x] Test dispatch failure → 200 with warning (existing behavior)

### Task 3.3: Quality checks

- [x] Run `make test`
- [x] Run `make lint`
- [x] Verify daemon starts cleanly with and without inbound config
- [x] Verify no unchecked implementation tasks remain

---

## Phase 4: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
