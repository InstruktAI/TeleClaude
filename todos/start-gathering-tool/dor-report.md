# DOR Report: start-gathering-tool

## Draft Assessment

### Gate 1: Intent & Success — PASS

Intent is clear: build the daemon-side tool that orchestrates gathering ceremonies. The input.md captures the full communication model (handshake, fan-out, injection), the talking piece with thought heartbeats, HITL participation, and the procedure update dependency. Requirements.md refines this into concrete success criteria with testable conditions.

### Gate 2: Scope & Size — NEEDS ATTENTION

This is a substantial piece of work: new MCP tool, in-memory state management, output monitoring, fan-out delivery, talking piece logic with timers, heartbeat injection, pass detection, phase management with breath structure, harvester role, history search during seed preparation, HITL support, and tests. Nine implementation tasks.

**Risk**: May push context limits in a single AI session. The mitigation is that the tasks are well-sequenced and the codebase patterns are established (the fan-out is modeled after `_notify_listeners`, injection uses `send_keys_existing_tmux`, monitoring uses `capture_pane`). A builder with the implementation plan should be able to execute without heavy exploration.

**Recommendation**: Keep as single todo for now. If the gate reviewer judges it too large, split into: (a) gathering state + MCP tool + session spawning + nested guard, (b) communication fabric + talking piece + heartbeats + phase management + harvester, (c) HITL + history search + tests.

### Gate 3: Verification — PASS

Success criteria are concrete and testable (15 conditions in requirements.md). Unit tests for state management, pass detection, phase transitions, breath structure, and attribution formatting. Integration tests (mocked tmux) for the full lifecycle including phase announcements, harvester signal, and history search invocation. Observable behavior: spawned sessions receive seed messages with identity assignment, speaking agent's output appears in all other sessions with attribution, harvester receives all messages but never holds the piece.

### Gate 4: Approach Known — PASS

Every component maps to an existing codebase pattern:

- Session spawning: `_start_local_session(direct=True)` — proven path
- Fan-out delivery: `_notify_listeners` loop in `session_listeners.py` — exact pattern
- Message injection: `tmux_bridge.send_keys_existing_tmux` — proven primitive
- Output monitoring: `OutputPoller.poll()` / `capture_pane` — established infrastructure
- In-memory state: `_active_pollers` pattern in `polling_coordinator.py` — asyncio.Lock-protected dict
- Timer-based injection: `asyncio.sleep` + `send_keys` — straightforward
- Phase management: Round counting with phase announcements — no new primitives needed
- Harvester: Same fan-out recipient logic, excluded from speaker order — data model concern only
- History search: `history.py --agent all <keywords>` — existing CLI tool, shell invocation during seed prep

No architectural unknowns. The output diff/baseline mechanism is new but simple in concept.

### Gate 5: Research Complete — PASS (N/A)

No third-party dependencies. All infrastructure is internal.

### Gate 6: Dependencies & Preconditions — PASS

- `direct=true` flag: delivered in 6157a769
- Gathering procedure doc: delivered in c12738c3
- Rhythm sub-procedures: listed as dependency in roadmap, but the tool accepts parameters directly — it doesn't need the sub-procedure docs to be built. The sub-procedures just provide defaults.

### Gate 7: Integration Safety — PASS

The gathering tool is entirely additive:

- New MCP tool handler (no changes to existing tools)
- New state module (`teleclaude/core/gathering.py`)
- Uses existing tmux primitives without modifying them
- Sessions spawned with `direct=true` have no notification side effects

Rollback: remove the tool handler and state module. No other code is affected.

### Gate 8: Tooling Impact — PASS (N/A)

No tooling or scaffolding changes.

## Open Questions

1. **Micro-pulse content**: What exactly goes in the heartbeat's signal refresh? For v1, proposed: participant count, gathering phase, rounds remaining. Richer pulse deferred.
2. **Human session resolution**: How exactly is the human's tmux session resolved? If invoked from Telegram, the caller's session IS the human's session. Needs verification against the adapter layer.
3. **Beat interval tuning**: Proposed 60s beats. May need adjustment after first live gathering. The tool accepts this as a parameter, so it's configurable.

## Assumptions

- Gatherings are ephemeral — in-memory state is acceptable (no SQLite table needed)
- The 1-second tmux send-keys delay is acceptable for conversational pace
- Output diffing via baseline snapshot is sufficient for feedback loop prevention
- Pattern matching for pass detection is conservative enough to avoid false positives
- The daemon process is stable during the ~15-30 minute duration of a typical gathering

## Verdict

**Draft assessment: likely PASS** pending gate reviewer confirmation on scope (Gate 2). All other gates are satisfied. The work is well-defined, the approach maps cleanly to existing patterns, and the risk profile is low.
