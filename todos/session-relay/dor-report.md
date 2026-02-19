# DOR Report: session-relay

## Gate Verdict

**Score: 9/10 — PASS**

Assessed: 2026-02-18 (gate phase)

### Gate 1: Intent & Success — PASS

Problem: `send_message` delivers to a session but there is no automatic relay of the response back. Agents must make tool calls for every exchange.

Outcome: bidirectional output relay between sessions after `send_message(direct=true)`. No tool calls after the handshake.

8 success criteria, all testable. Clear scope boundary: 1:1 relay only, gathering orchestration is a separate todo.

### Gate 2: Scope & Size — PASS

3 tasks:

1. Relay primitive (new file: `session_relay.py`)
2. Handler wiring (small addition to `handlers.py`)
3. Tests

Single new module + one handler modification. Well within single-session capacity. No cross-cutting changes.

### Gate 3: Verification — PASS

- Unit tests: relay CRUD, fan-out to N-1 participants, baseline prevents feedback loops, cleanup on session end, concurrent relays
- Integration tests (mocked tmux): bidirectional relay via send_message, attribution formatting, cleanup, existing behavior unchanged
- Edge cases identified: scrollback overflow (conservative baseline), race conditions (asyncio.Lock)
- `make test` + `make lint`

### Gate 4: Approach Known — PASS

| Component           | Pattern source                                     | Confirmed at                   |
| ------------------- | -------------------------------------------------- | ------------------------------ |
| Output capture      | `capture_pane`                                     | tmux_bridge.py:952             |
| Message injection   | `send_keys_existing_tmux`                          | tmux_bridge.py:470             |
| In-memory state     | `_active_pollers` + `asyncio.Lock`                 | polling_coordinator.py:618-619 |
| Caller session info | `caller_session_id` param                          | handlers.py:532                |
| Session DB lookup   | `Session.tmux_session_name`                        | db_models.py:25                |
| Direct flag         | `if not direct: await self._register_listener_...` | handlers.py:537                |

The baseline snapshot/delta mechanism is new but conceptually simple: capture pane state, diff against baseline, deliver delta, update baseline. No unknowns.

### Gate 5: Research Complete — PASS (N/A)

No third-party dependencies. All infrastructure is internal.

### Gate 6: Dependencies & Preconditions — PASS

| Dependency         | Status                                               |
| ------------------ | ---------------------------------------------------- |
| `direct=true` flag | Delivered: 6157a769. Verified at handlers.py:533,537 |

No other dependencies. No external systems.

### Gate 7: Integration Safety — PASS

Entirely additive:

- New module `teleclaude/core/session_relay.py` — no existing files modified except handlers.py
- Handler modification: small addition after existing `send_message` delivery path, gated by `direct=true` — existing behavior unchanged when `direct=false`
- Rollback: remove the new module and handler addition. Zero blast radius.

### Gate 8: Tooling Impact — PASS (N/A)

No tooling or scaffolding changes.

## Assumptions

- 1-second polling cadence sufficient for conversational pace (matches existing OutputPoller)
- tmux pane scrollback is deep enough for baseline tracking within a conversation turn
- `caller_session_id` is reliably populated when `direct=true` is used (agents always have a session)
- In-memory relay state acceptable (relay is ephemeral — lost on daemon restart, agents re-establish)

## Open Questions

None. The scope is tight and fully specified.

## Verdict

**PASS — score 9/10.** All eight gates satisfied with strong evidence. Scope is small and focused. Every component maps to a confirmed codebase pattern. No open questions, no blockers. Higher score than the parent todo because of the tighter scope and simpler dependency graph.

Ready for build phase.
