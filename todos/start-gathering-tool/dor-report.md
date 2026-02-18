# DOR Report: start-gathering-tool

## Gate Verdict

**Score: 8/10 — PASS**

Assessed: 2026-02-18 (re-gate after scope expansion)

Previous gate: 8/10 PASS (same date, before Tasks 1-2 added).
This re-gate validates the expanded scope: session relay primitive + 1:1 relay via send_message.

### Gate 1: Intent & Success — PASS

Intent is explicit and strengthened by the expansion. Two use cases clearly articulated:

- **1:1 direct conversations** — bidirectional relay after `send_message(direct=true)` handshake
- **Multi-party gathering ceremonies** — turn-managed relay with talking piece, heartbeats, phases, harvester

Three artifacts align:

- `input.md`: full design spec — communication model, relay as core primitive, both use cases, identity/seed, talking piece, harvester, breath structure, HITL, history signals.
- `requirements.md`: 20 testable success criteria (5 for 1:1 relay, 15 for gathering), scoped in/out boundaries, key files, constraints, risks.
- `implementation-plan.md`: 11 tasks with data models, relay primitive, 1:1 wiring, orchestrator loop, build sequence, risk mitigations.

No ambiguity in what or why.

### Gate 2: Scope & Size — PASS (conditional)

Eleven tasks across two new modules (`session_relay.py`, `gathering.py`) plus MCP wiring. Larger than the previous 9-task plan, but architecturally cleaner.

**Why it passes despite scope increase:**

1. The relay primitive (Task 1) follows proven codebase patterns — no new infrastructure concepts.
2. The 1:1 wiring (Task 2) is a small addition to `send_message` handler — create relay after delivery.
3. **The split point is now earlier and stronger.** After Task 2, 1:1 conversations work independently. This is the highest-value deliverable (per Mo: "1:1 will be the most important communication mode"). Tasks 3-11 build gathering on top. If context exhausts after Task 2, the most important use case is already delivered.

**Conditional:** If context is exhausted during build:

- After Task 2: 1:1 relay is complete and usable. Gathering becomes a follow-up todo.
- After Task 5 (gathering orchestrator): gathering core works without HITL, history search, or comprehensive tests. Tasks 6-11 can be a follow-up.

### Gate 3: Verification — PASS

20 success criteria, all testable:

**1:1 relay (5 criteria):**

- `send_message(direct=true)` starts bidirectional relay
- Both agents' output relayed with attribution
- No additional tool calls after handshake
- Baseline snapshot prevents feedback loops
- Relay ends cleanly on session end

**Gathering (15 criteria):**

- Unit tests: state CRUD, pass detection (positive + negative), attribution formatting, beat advancement, phase transitions, breath structure.
- Integration tests (mocked tmux): full lifecycle through all phases, fan-out delivery, heartbeat injection, early pass, harvester signal, nested guard.
- Observable: `make test`, `make lint`.

Edge cases identified: feedback loop prevention (baseline snapshot), pass detection false positives (conservative phrase matching), output monitoring latency (N+1 seconds).

### Gate 4: Approach Known — PASS

All components verified against codebase:

| Component           | Pattern source                                                     | Verified        |
| ------------------- | ------------------------------------------------------------------ | --------------- |
| Session spawning    | `_start_local_session(direct=True)` at handlers.py:323             | Yes             |
| Session result      | Returns `session_id` + `tmux_session_name` at handlers.py:386      | Yes             |
| Caller session info | `caller_session_id` available in `send_message` at handlers.py:532 | Yes             |
| Session DB lookup   | `Session.tmux_session_name` at db_models.py:25                     | Yes             |
| Fan-out delivery    | `_notify_listeners` in session_listeners.py                        | Yes             |
| Message injection   | `send_keys_existing_tmux` in tmux_bridge.py                        | Yes             |
| Output monitoring   | `OutputPoller.poll()` / `capture_pane` in output_poller.py         | Yes             |
| In-memory state     | `_active_pollers` + `_poller_lock` in polling_coordinator.py:618   | Yes             |
| Timer injection     | `asyncio.sleep` + `send_keys`                                      | Straightforward |
| Phase management    | Round counting — no new primitives                                 | Straightforward |
| Harvester           | Data model concern — excluded from speaker_order                   | Straightforward |
| History search      | `history.py --agent all` — existing CLI                            | Yes             |

**New verification (Task 2 wiring):** `send_message` handler at line 527 has `caller_session_id` parameter. Session DB has `tmux_session_name` field. Both sessions' relay data is resolvable via `db.get_session()`. No new infrastructure needed.

### Gate 5: Research Complete — PASS (N/A)

No third-party dependencies. All infrastructure is internal. Art of Hosting third-party docs are reference material, not a build dependency.

### Gate 6: Dependencies & Preconditions — PASS

| Dependency                                             | Status                                                                                                                  |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| `direct=true` flag on `send_message` / `start_session` | Delivered: 6157a769. Verified at handlers.py:331,533                                                                    |
| Gathering procedure doc                                | Delivered: c12738c3                                                                                                     |
| Rhythm sub-procedures                                  | Soft dependency. Tool accepts all params directly. Sub-procedures provide operational defaults, not build prerequisites |
| Agent Direct Conversation procedure update             | Out of scope (separate doc-only todo)                                                                                   |

### Gate 7: Integration Safety — PASS

Entirely additive:

- New module `teleclaude/core/session_relay.py` — the relay primitive. No modifications to existing modules.
- New module `teleclaude/core/gathering.py` — gathering state and orchestrator. No modifications to existing modules.
- New MCP tool handler (`start_gathering`) — no changes to existing handlers.
- Small addition to `send_message` handler — creates relay after delivery when `direct=true`. Existing behavior unchanged.
- Uses existing tmux primitives read-only (no signature changes).
- Sessions spawned with `direct=true` — no notification side effects.

Rollback: remove the new modules and handler additions. Zero blast radius on existing functionality.

### Gate 8: Tooling Impact — PASS (N/A)

No tooling or scaffolding changes.

## Open Questions (non-blocking)

1. **Micro-pulse content**: For v1: participant count, gathering phase, rounds remaining. Richer pulse deferred. **Non-blocking** — string parameter, easily extended.
2. **Human session resolution**: Human's tmux session resolved from caller's session. When invoked from Telegram, the caller's session IS the human's session. **Non-blocking** — builder verifies during Task 7.
3. **Beat interval tuning**: 60s beats proposed. Tool accepts as parameter. **Non-blocking** — tunable at runtime.
4. **Relay cleanup on daemon restart**: Relays are in-memory. Lost on restart. **Non-blocking** — both 1:1 conversations and gatherings are ephemeral.

## Assumptions (validated)

- Gatherings and 1:1 relays are ephemeral — in-memory state acceptable. Confirmed: no persistence requirement.
- 1-second tmux send-keys delay acceptable — requirements.md documents expected latency.
- Baseline snapshot sufficient for feedback loop prevention — well-specified in requirements.md.
- Pass detection pattern matching conservative enough — phrase-level, not word-level.
- `caller_session_id` reliably available in `send_message` — confirmed at handlers.py:532.
- Both `session_id` and `tmux_session_name` available from session creation and DB — confirmed.

## Verdict

**PASS — score 8/10.** All eight gates satisfied. Scope expanded from 9 to 11 tasks but architecture is cleaner (relay as shared foundation) and the first deliverable is stronger (1:1 after Task 2 vs gathering-only after old Task 4). The conditional split point after Task 2 delivers the highest-value use case independently. Four open questions are non-blocking and resolvable during implementation.

Ready for build phase.
