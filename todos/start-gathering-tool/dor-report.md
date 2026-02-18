# DOR Report: start-gathering-tool

## Gate Verdict

**Score: 8/10 — PASS**

Assessed: 2026-02-18 (gate phase)

### Gate 1: Intent & Success — PASS

Intent is explicit: build the daemon-side `start_gathering` MCP tool that orchestrates gathering ceremonies. Three artifacts align:

- `input.md`: full design spec — communication model (handshake-only, daemon fan-out), talking piece with thought heartbeats, harvester role, breath structure, HITL, history signals, procedure update dependency.
- `requirements.md`: 15 testable success criteria, scoped in/out boundaries, key files, constraints, risks.
- `implementation-plan.md`: 9 tasks with data models, orchestrator loop, build sequence, risk mitigations.

No ambiguity in what or why.

### Gate 2: Scope & Size — PASS (conditional)

Nine implementation tasks across one new module (`teleclaude/core/gathering.py`) plus MCP wiring. This is the largest single todo in the pipeline.

**Why it passes:** Every task maps to a proven codebase pattern (verified):

- `_start_local_session(direct=True)` — confirmed at `handlers.py:323`, `direct` flag skips listener registration at line 364.
- `send_keys_existing_tmux` — confirmed in `tmux_bridge.py`, used by 16 files.
- `capture_pane` — confirmed in `output_poller.py`, used by 14 files.
- `_active_pollers` with `asyncio.Lock` — confirmed at `polling_coordinator.py:618-640`, exact pattern for gathering state.
- `_notify_listeners` / `deliver_listener_message` — confirmed in `session_listeners.py` and `tmux_delivery.py`.

The builder needs minimal exploration — the plan provides data models, function signatures, and the orchestrator loop. Tasks are sequential with clear boundaries.

**Conditional:** If a builder exhausts context before completing all 9 tasks, the natural split point is after Task 4 (communication fabric + talking piece). Tasks 5-9 (HITL, phase management, history search, guard, tests) can become a follow-up todo. This split should be decided during build, not now.

### Gate 3: Verification — PASS

15 success criteria in requirements.md, all testable:

- Unit tests: state CRUD, pass detection (positive + negative), attribution formatting, beat advancement, phase transitions, breath structure.
- Integration tests (mocked tmux): full lifecycle through all phases, fan-out delivery, heartbeat injection, early pass, harvester signal, nested guard.
- Observable: `make test`, `make lint`.

Edge cases identified: feedback loop prevention (baseline snapshot), pass detection false positives (conservative phrase matching), output monitoring latency (N+1 seconds).

### Gate 4: Approach Known — PASS

All components verified against codebase:

| Component         | Pattern source                                                   | Verified        |
| ----------------- | ---------------------------------------------------------------- | --------------- |
| Session spawning  | `_start_local_session(direct=True)` at handlers.py:323           | Yes             |
| Fan-out delivery  | `_notify_listeners` in session_listeners.py                      | Yes             |
| Message injection | `send_keys_existing_tmux` in tmux_bridge.py                      | Yes             |
| Output monitoring | `OutputPoller.poll()` / `capture_pane` in output_poller.py       | Yes             |
| In-memory state   | `_active_pollers` + `_poller_lock` in polling_coordinator.py:618 | Yes             |
| Timer injection   | `asyncio.sleep` + `send_keys`                                    | Straightforward |
| Phase management  | Round counting — no new primitives                               | Straightforward |
| Harvester         | Data model concern — excluded from speaker_order                 | Straightforward |
| History search    | `history.py --agent all` — existing CLI                          | Yes             |

The output diff/baseline mechanism is new but conceptually simple and well-specified.

**Minor correction:** DOR draft said "asyncio.Lock-protected dict" — actual pattern is `asyncio.Lock`-protected `set`. The gathering will use a `dict`, same lock pattern. No material impact.

### Gate 5: Research Complete — PASS (N/A)

No third-party dependencies. All infrastructure is internal. Art of Hosting third-party docs are already delivered and are reference material, not a build dependency.

### Gate 6: Dependencies & Preconditions — PASS

| Dependency                                             | Status                                                                                                                  |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| `direct=true` flag on `send_message` / `start_session` | Delivered: 6157a769. Verified at handlers.py:331,397                                                                    |
| Gathering procedure doc                                | Delivered: c12738c3                                                                                                     |
| Rhythm sub-procedures                                  | Soft dependency. Tool accepts all params directly. Sub-procedures provide operational defaults, not build prerequisites |
| Agent Direct Conversation procedure update             | Out of scope (separate doc-only todo)                                                                                   |

The roadmap declares `after: gathering-rhythm-subprocedures` — this is an operational dependency (defaults), not a build blocker. The tool is fully buildable without it.

### Gate 7: Integration Safety — PASS

Entirely additive:

- New MCP tool handler — no changes to existing handlers.
- New module `teleclaude/core/gathering.py` — no modifications to existing modules.
- Uses existing tmux primitives read-only (no signature changes).
- Sessions spawned with `direct=true` — no notification side effects.

Rollback: remove the tool handler and state module. Zero blast radius.

### Gate 8: Tooling Impact — PASS (N/A)

No tooling or scaffolding changes.

## Open Questions (non-blocking)

1. **Micro-pulse content**: For v1, proposed: participant count, gathering phase, rounds remaining. Richer pulse (channel activity, pipeline state) deferred. **Non-blocking** — the micro-pulse is a string parameter, easily extended.
2. **Human session resolution**: The human's tmux session is resolved from the caller's session. When invoked from Telegram, the caller's session IS the human's session. **Non-blocking** — builder can verify against adapter layer during Task 5.
3. **Beat interval tuning**: 60s beats proposed. Tool accepts as parameter. **Non-blocking** — tunable at runtime.

## Assumptions (validated)

- Gatherings are ephemeral — in-memory state acceptable. Confirmed: no persistence requirement in input.md, requirements.md explicitly states "gatherings are ephemeral."
- 1-second tmux send-keys delay acceptable — requirements.md documents expected latency (~N seconds per message).
- Baseline snapshot sufficient for feedback loop prevention — well-specified in requirements.md output monitoring design section.
- Pass detection pattern matching conservative enough — requirements.md specifies phrase-level matching, not word-level.
- Daemon stable for ~15-30 minute gathering duration — reasonable given typical daemon uptime.

## Verdict

**PASS — score 8/10.** All eight gates satisfied. Scope is at the upper bound but justified by pattern coverage and well-sequenced tasks. The conditional split point (after Task 4) provides a safety valve if context is exhausted during build. Three open questions are non-blocking and resolvable during implementation.

Ready for build phase.
