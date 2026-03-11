# Input: session-adaptive-runtime

Split from parent `session-runtime-overhaul` — Phase 3 (Render-Aware Runtime),
Phase 4 (Wake-Driven Capture), and Phase 6 (Validation and Documentation).

Depends on: `session-polling-baseline` (replay corpus + immediate fixes must land first).

## What

### Phase 3: Render-Aware Session Runtime

1. **Extract Codex render semantics** — Move all Codex-specific parsing, state, and
   event synthesis from `polling_coordinator.py` into a new
   `teleclaude/core/codex_render_semantics.py`. The extraction makes the three-lane
   model explicit in code structure. See parent implementation plan Tasks 3.1 for exact
   items to move (constants, ANSI helpers, parser functions, state classes, event
   synthesis). Re-export `seed_codex_prompt_from_message` for backward compat.

2. **Introduce SessionRuntime actor** — Create `teleclaude/core/session_runtime.py`
   with `SessionRuntime` dataclass owning per-session state (codex_input, codex_turn,
   metrics, cadence, wake_dirty, active_agent) and `SessionRuntimeRegistry` replacing
   module-level dicts. Update `poll_and_send_output()` to use runtime from registry.

### Phase 4: Wake-Driven Capture and Adaptive Cadence

3. **Wake/dirty signal via pipe-pane** — Attach `pipe-pane -o` when SessionRuntime
   starts for Codex sessions. FIFO in per-session tmp dir. Asyncio coroutine sets
   `runtime.wake_dirty = True` on bytes. Reconciliation snapshot on startup, reconnect,
   headless bootstrap, and audit-triggered drift recovery (pipe-pane is prospective only).

4. **Adaptive cadence state machine** — `CadenceState` with fast (0.5s), slow (5.0s),
   audit (30.0s) modes. Transitions: fast->slow after `idle_transition_s` (10s) without
   wake; slow->fast on wake/input/trigger. New config keys under `polling:` section.
   Update `config.sample.yml`, config wizard, `teleclaude-config.md`.

5. **Conditional capture** — Skip `capture-pane` when idle, not dirty, not audit-due.
   Capture on wake, turn activity, startup, or reconnect.

### Phase 6: Validation and Documentation

6. **Performance instrumentation** — Runtime counters: capture_count, wake_count,
   skip_count, idle_transition_count, tmux_subprocess_count. Emit at existing metrics
   interval with matched idle-window labels.

7. **Test realignment** — Update tests that overfit old hot-loop probe order. Assert
   behavioral contracts instead.

8. **Documentation update** — Rewrite `output-polling.md` with three-lane model,
   SessionRuntime, wake-driven capture, adaptive cadence, lane-authority table.
   Update `tmux-management.md` with pipe-pane wake signal, headless reconciliation,
   tmp cleanup.

9. **Integration smoke** — Full suite run, daemon restart safety, regression checks,
   demo validation.

## Why

This is the core architectural change: replacing the monolithic fixed-rate polling loop
with a render-aware session runtime that captures snapshots only when meaningful output
occurred. Idle sessions back off from 1 capture/s to ~1 capture/30s (audit only),
reducing steady-state tmux churn by ~5x for idle sessions while preserving all Codex
live semantic inference.

## Success Criteria

- Codex semantic inference emits same tool_use/tool_done/user_prompt_submit events
- agent_stop remains hook-authoritative
- Idle sessions skip capture between audit intervals
- Active sessions capture on wake signals at 0.5s cadence
- SessionRuntime owns all per-session state as a unit
- Config surface changes documented (sample, wizard, spec)
- Docs describe three-lane model, not single diff loop
- All tests pass; no behavioral regressions
