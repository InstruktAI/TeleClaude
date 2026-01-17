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
| All external entry points map to internal command models via a single normalization layer. | `teleclaude/core/command_mapper.py:74` + adapters | Telegram/REST/Redis → `CommandMapper` → `AdapterClient.handle_internal_command` | `tests/unit/test_command_mapper.py::test_map_telegram_new_session`, `tests/unit/test_command_mapper.py::test_map_rest_message`, `tests/integration/test_ai_to_ai_session_init_e2e.py::test_ai_to_ai_session_initialization_with_claude_startup` | ❌ |
| REST/Redis code paths no longer branch on adapter-specific behavior in core handlers. | `teleclaude/daemon.py:1960` | `AdapterClient.handle_internal_command` → `Daemon.handle_command` | `tests/unit/test_daemon.py::test_new_session_auto_command_agent_then_message` | ⚠️ |
| Core handlers accept typed internal commands consistently. | `teleclaude/daemon.py:1960` | `CommandEventContext.internal_command` → `Daemon.handle_command` | `tests/unit/test_session_launcher.py::test_create_session_runs_auto_command_after_create` | ⚠️ |
| Tests updated/added to cover normalization layer and ensure no behavior regressions. | `tests/unit/test_command_mapper.py` | n/a | `tests/unit/test_rest_adapter.py`, `tests/unit/test_redis_adapter.py` | ⚠️ |

**Verification notes:**
- Telegram command handlers (new_session/rename/cd/agent) still call `handle_event` directly and bypass `CommandMapper`, so normalization is not applied uniformly. `teleclaude/adapters/telegram/command_handlers.py:90`. 
- REST `end_session`, `agent_restart`, and `get_transcript` still bypass normalization and call handlers directly. `teleclaude/adapters/rest_adapter.py:343`.
- Redis normalization currently maps unrecognized commands (including `list_sessions`, `list_projects`, `list_todos`, `get_session_data`, `get_computer_info`) to `SystemCommand`, which routes to `system_command` instead of command handlers.

### Integration Test Check
- Main flow integration test exists: yes
- Test file: `tests/integration/test_ai_to_ai_session_init_e2e.py`
- Coverage: Redis inbound `/new_session` path, session creation, response envelope
- Quality: Uses real daemon wiring with mocked external systems; acceptable for integration baseline

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Normalize all external inputs into internal command models before core handlers. | ❌ | Telegram/REST still call `handle_event` directly; Redis command mapping misroutes list/get commands. |
| Treat REST/Redis as transports only (parse/validate/map). | ⚠️ | REST `end_session`/`agent_restart` still call core handlers directly. |
| Unify handler signatures to accept internal command models. | ⚠️ | `new_session` uses `CreateSessionCommand`, but other command handlers still rely on raw payloads. |
| Keep behavior and ordering intact. | ⚠️ | Redis list/get commands now route to system command handler (no responses). |
| Tests updated/added to cover normalization layer and regressions. | ⚠️ | Mapper tests exist, but no coverage for Redis list/get commands or invalid notifications. |

## Critical Issues (must fix)

- [code] `teleclaude/core/command_mapper.py:181` - Redis command strings like `list_sessions`, `list_projects`, `list_todos`, `get_session_data`, and `get_computer_info` now fall through to `SystemCommand`, which dispatches `system_command` instead of command handlers. Remote cache pulls and request/response queries will return “Unknown system command” and break cross‑computer reads.
  - Suggested fix: Introduce an internal command model that preserves command event types (or map these command names to a generic `CommandEvent` internal model), and ensure `handle_internal_command` dispatches the correct TeleClaude command events for list/get operations.

## Important Issues (should fix)

- [code] `teleclaude/adapters/telegram/command_handlers.py:90` - Telegram command handlers (e.g., `/new_session`, `/rename`, `/cd`, `/claude`) still call `handle_event` directly instead of normalizing through `CommandMapper`, so external inputs are not uniformly normalized as required.
  - Suggested fix: Route these handlers through `CommandMapper.map_telegram_input` and `AdapterClient.handle_internal_command` (or create normalized command models for these commands).

- [code] `teleclaude/adapters/rest_adapter.py:343` - REST `end_session`, `agent_restart`, and `get_transcript` bypass the normalization layer and call core handlers directly, violating the “single normalization layer” requirement.
  - Suggested fix: Add internal command models (or a generic command wrapper) for these endpoints and route them through `handle_internal_command`.

- [errors] `teleclaude/core/command_mapper.py:91` - `stop_notification` and `input_notification` no longer validate argument length or log decode failures; malformed inputs now emit agent events with empty session IDs and silent decode errors.
  - Suggested fix: Restore argument validation and warning logs; return early on invalid input to avoid downstream errors.

## Suggestions (nice to have)

- [types] `teleclaude/types/commands.py:11` - `CommandType.SEND_AGENT_COMMAND` has no corresponding `EventType` handler, which will produce `NO_HANDLER` errors if used. Consider removing it or wiring it to a concrete handler to keep invariants aligned.

## Strengths

- Command normalization layer is centralized in `CommandMapper` and covered by unit tests for REST/Redis/Telegram basics.
- Session creation flow now carries internal command objects through `AdapterClient`, making call paths easier to reason about.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Fix Redis command normalization so list/get requests dispatch to command handlers (not `system_command`).
2. Route remaining Telegram/REST entry points through the normalization layer to meet requirements.

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| Redis command strings fall through to system_command handler | Modified `handle_internal_command` to use command name as event type for SystemCommand, allowing query/list commands to route properly | 0a9dc17 |
| Telegram /new_session, /claude, /gemini, /codex, /agent_resume bypass normalization | Updated handlers to use CommandMapper.map_telegram_input() and handle_internal_command | 77b8de7 |
| REST end_session, agent_restart, get_transcript bypass normalization | Added mappings in CommandMapper, updated endpoints to use handle_internal_command, added session_id field to SystemCommand | 9bb77b8 |
| stop_notification and input_notification lack validation | Added argument count validation and decode failure logging, return noop for invalid inputs | e41a058 |
