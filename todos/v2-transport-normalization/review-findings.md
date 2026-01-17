# Code Review: v2-transport-normalization

**Reviewed**: 2026-01-17
**Reviewer**: Codex

## Completeness Verification

### Implementation Plan Status
- Unchecked tasks: 0 → None
- Silent deferrals found: no

### Success Criteria Verification

| Criterion | Implemented | Call Path | Test | Status |
|-----------|-------------|-----------|------|--------|
| All external entry points map to internal command models via a single normalization layer. | `teleclaude/core/command_mapper.py:1` + `teleclaude/core/adapter_client.py:773` | Telegram/REST/Redis → `CommandMapper` → `AdapterClient.handle_internal_command` → `Daemon.handle_command` | `tests/unit/test_command_mapper.py::test_map_telegram_new_session`, `tests/unit/test_command_mapper.py::test_map_rest_message` | ❌ |
| REST/Redis code paths no longer branch on adapter-specific behavior in core handlers. | `teleclaude/daemon.py:1976` | `AdapterClient.handle_internal_command` → `Daemon.handle_command` | `tests/unit/test_daemon.py::test_new_session_auto_command_agent_then_message` | ⚠️ |
| Core handlers accept typed internal commands (or normalized request objects) consistently. | `teleclaude/daemon.py:1976` | `CommandEventContext.internal_command` → `Daemon.handle_command` | `tests/unit/test_session_launcher.py::test_create_session_runs_auto_command_after_create` | ⚠️ |
| Tests updated/added to cover normalization layer and ensure no behavior regressions. | `tests/unit/test_command_mapper.py` | n/a | `tests/unit/test_rest_adapter.py`, `tests/unit/test_redis_adapter.py` | ⚠️ |

**Verification notes:**
- Telegram command handlers and callback flows still call `handle_event` directly for `/rename`, `/cd`, `/agent_restart`, and button-driven session/agent starts, so those inputs bypass `CommandMapper`.
- REST `end_session` and `get_transcript` still bypass `CommandMapper`/`handle_internal_command`.
- Internal command dispatch does not propagate `message_id`, so Telegram pre/post handlers don’t run for normalized command paths, violating the UX cleanup contract.

### Integration Test Check
- Main flow integration test exists: yes
- Test file: `tests/integration/test_ai_to_ai_session_init_e2e.py`
- Coverage: Redis inbound `/new_session` → normalization → session creation → response envelope → output listener
- Quality: Uses real daemon wiring with mocked external systems; acceptable integration baseline

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Normalize all external inputs into internal command models before core handlers. | ❌ | Multiple Telegram and REST entry points still call `handle_event` or core handlers directly. |
| Treat REST/Redis as transports only (parse/validate/map). | ⚠️ | REST `end_session` and `get_transcript` bypass normalization. |
| Unify handler signatures to accept internal command models. | ⚠️ | Internal commands are supported, but several entry points still send raw payloads. |
| Keep behavior and ordering intact. | ⚠️ | Telegram command cleanup no longer runs for normalized commands (missing `message_id`). |
| Tests updated/added to cover normalization layer and regressions. | ⚠️ | Mapper tests exist, but no coverage for remaining unnormalized entry points or message-id cleanup. |

## Critical Issues (must fix)

- [code] `teleclaude/adapters/telegram/command_handlers.py:152` - Telegram command handlers and callback flows still bypass the normalization layer (e.g., `/rename`, `/cd`, `/agent_restart`, session/agent selection buttons), violating the “single normalization layer” requirement.
  - Suggested fix: Route these handlers through `CommandMapper.map_telegram_input()` (or add normalized models) and dispatch via `handle_internal_command`.

- [code] `teleclaude/adapters/rest_adapter.py:350` - REST `end_session` and `get_transcript` still call core handlers/`handle_event` directly, bypassing normalization and violating the REST-as-transport requirement.
  - Suggested fix: Map these endpoints via `CommandMapper.map_rest_input()` and dispatch with `handle_internal_command` (or add explicit internal commands where needed).

## Important Issues (should fix)

- [code] `teleclaude/core/adapter_client.py:800` - `handle_internal_command` drops `message_id`, so Telegram pre/post handler cleanup is skipped for normalized commands, leading to message clutter and violating the UX deletion contract.
  - Suggested fix: Add `message_id` to `InternalCommand` (or pass it into `handle_internal_command`) and include it in the payload so `_call_pre_handler`/`_call_post_handler` execute.

- [comments] `teleclaude/adapters/telegram_adapter.py:212` - `_handle_simple_command` docstring claims it emits `message_id`, but the normalized path no longer includes it.
  - Suggested fix: Either update the docstring or restore message_id propagation as above.

- [tests] `tests/unit/test_command_mapper.py:1` - No test coverage that normalized Telegram commands still trigger UX cleanup (message_id propagation) or that remaining Telegram/REST entry points are normalized.
  - Suggested fix: Add unit tests around `AdapterClient.handle_internal_command`/Telegram handlers to assert message_id propagation and normalization coverage for rename/cd/agent_restart/get_transcript/end_session.

## Suggestions (nice to have)

- [types] `teleclaude/types/commands.py:211` - `SystemCommand` defines `session_id` twice and assigns it twice, which obscures invariants and makes the type harder to reason about.
  - Suggested fix: Remove the duplicate field/assignment and keep a single canonical `session_id` field.

## Strengths

- Central `CommandMapper` abstraction and `handle_internal_command` flow improve clarity and reduce transport leakage for the paths that use them.
- Redis inbound normalization and response envelopes are now consistently handled in one place.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Normalize all remaining Telegram/REST entry points (including callback flows) through `CommandMapper` + `handle_internal_command`.
2. Restore message_id propagation for normalized command paths to preserve UX cleanup behavior.
