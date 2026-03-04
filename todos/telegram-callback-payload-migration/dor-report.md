# DOR Report: telegram-callback-payload-migration

## Draft Assessment

### Gate 1: Intent & Success
**Pass.** Problem statement is explicit: migrate hardcoded per-agent callback payloads to
`AgentName`-derived canonical format. Success criteria are concrete and testable (enum
changes, legacy parsing, dynamic keyboard, test coverage).

### Gate 2: Scope & Size
**Pass.** Atomic change touching two files (`callback_handlers.py`, `telegram_adapter.py`)
plus test file. Fits a single session. No cross-cutting concerns beyond the Telegram adapter.

### Gate 3: Verification
**Pass.** Verification through unit tests (legacy parsing, new parsing, dynamic keyboard),
plus `make test` and `make lint`. Edge cases identified: unknown agent in payload, disabled
agents in keyboard, 64-byte callback_data limit.

### Gate 4: Approach Known
**Pass.** Pattern is straightforward: enum reduction, fallback map for legacy, loop over
`get_enabled_agents()` for keyboard. Similar patterns exist in the codebase (e.g.,
`AgentName.from_str()` for validation, `get_enabled_agents()` already used elsewhere).

### Gate 5: Research Complete
**Automatically satisfied.** No third-party dependencies introduced or modified.

### Gate 6: Dependencies & Preconditions
**Pass.** Depends on `default-agent-resolution` (delivered 2026-03-05). `AgentName` enum
and `get_enabled_agents()` are stable. No config changes needed. No new env vars.

### Gate 7: Integration Safety
**Pass.** Change is incremental. Legacy payloads remain functional. No breaking change to
external APIs or message formats. Rollback is straightforward (revert to per-agent enums).

### Gate 8: Tooling Impact
**Automatically satisfied.** No tooling or scaffolding changes.

## Assumptions

- Legacy buttons in Telegram chats will eventually expire (Telegram does not store inline
  keyboards indefinitely). The legacy map is a bridge, not permanent.
- `get_enabled_agents()` returns agents in stable order (verified: it iterates `KNOWN_AGENT_IDS`
  which is a tuple from `AgentName.choices()`).
- The `auto_command` format `"agent {name}"` and `"agent_resume {name}"` is consumed by
  `CommandMapper.map_telegram_input` and does not need to change for this migration.

## Open Questions

None. All design decisions are grounded in codebase evidence.
