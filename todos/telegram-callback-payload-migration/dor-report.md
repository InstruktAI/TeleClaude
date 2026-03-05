# DOR Report: telegram-callback-payload-migration

## Gate Verdict: PASS (score 9/10)

Assessed by gate worker on 2026-03-05. All eight DOR gates satisfied.

---

### Gate 1: Intent & Success — Pass

Problem statement is explicit: migrate hardcoded per-agent callback payloads to
`AgentName`-derived canonical format. Success criteria are concrete and testable —
enum changes, legacy parsing, dynamic keyboard, test coverage all have clear
observable outcomes.

### Gate 2: Scope & Size — Pass

Atomic change touching two primary files (`callback_handlers.py`, `telegram_adapter.py`)
plus test file. No cross-cutting concerns beyond the Telegram adapter. Fits a single
AI session without context exhaustion.

### Gate 3: Verification — Pass

Unit tests defined for: new format parsing, legacy format parsing, dynamic keyboard
with full and partial agent sets, graceful rejection of unknown agents, correct
`auto_command` generation. `make test` and `make lint` as verification commands.
Edge cases identified: unknown agent, disabled agents, 64-byte callback limit.

### Gate 4: Approach Known — Pass

Pattern is straightforward: enum reduction, static fallback map for legacy, loop over
`get_enabled_agents()` for keyboard. Existing patterns confirmed in codebase:
- `AgentName.from_str()` for validation (agents.py:19)
- `get_enabled_agents()` returns stable-order tuple from `KNOWN_AGENT_IDS` (agents.py:46)
- `_build_project_keyboard(prefix)` generates `f"{prefix}:{idx}"` buttons (confirmed by test)
- `auto_command` format `"agent {name}"` / `"agent_resume {name}"` passed through
  `CommandMapper.map_telegram_input` metadata (command_mapper.py:118)

### Gate 5: Research Complete — Automatically Satisfied

No third-party dependencies introduced or modified.

### Gate 6: Dependencies & Preconditions — Pass

Depends on `default-agent-resolution` (delivered 2026-03-05). `AgentName` enum and
`get_enabled_agents()` are stable. No config changes, no new env vars.

### Gate 7: Integration Safety — Pass

Incremental change. Legacy payloads remain functional via `LEGACY_ACTION_MAP`. No
breaking change to external APIs or message formats. Rollback is straightforward
(revert to per-agent enums).

### Gate 8: Tooling Impact — Automatically Satisfied

No tooling or scaffolding changes.

---

## Plan-to-Requirement Fidelity

Every implementation task traces to a requirement:

| Requirement | Plan Task(s) |
|---|---|
| Replace per-agent `CallbackAction` enum values | Task 1.1 |
| Replace hardcoded `event_map` and `mode_map` | Tasks 1.4, 1.5 |
| Build heartbeat keyboard dynamically | Task 1.6 |
| Parse legacy callback payloads | Tasks 1.2, 1.3 |
| Add tests for both formats | Task 2.1 |

No contradictions found. Plan prescribes `AgentName`-derived lookups exactly as
requirements specify. `auto_command` format in plan matches existing codebase
format confirmed in `command_mapper.py`.

## Verified Assumptions

- `get_enabled_agents()` returns agents in stable order — confirmed: iterates
  `KNOWN_AGENT_IDS` which is a tuple from `AgentName.choices()`, and Python enums
  preserve definition order.
- `auto_command` format `"agent {name}"` consumed by `CommandMapper.map_telegram_input`
  — confirmed at `command_mapper.py:118`.
- New payload format stays within Telegram's 64-byte limit — worst case
  `arsel:gemini:very_long_bot_username` is well under 64 bytes.
- `_build_project_keyboard(prefix)` generates `f"{prefix}:{idx}"` — confirmed by
  test assertion in `test_telegram_menus.py:108`.

## Builder Notes

- **Keyboard ordering change:** Current hardcoded order is Claude→Gemini→Codex.
  `get_enabled_agents()` follows enum definition order: Claude→Codex→Gemini. The
  dynamic keyboard will swap the last two rows. This is acceptable and a natural
  consequence of data-driven generation, but worth being aware of.

## Blockers

None. All design decisions are grounded in codebase evidence.
