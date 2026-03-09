# Requirements: codex-render-semantic-runtime

## Goal

Build a render-aware session runtime that preserves Codex live semantic inference from
tmux-rendered state while reducing idle tmux overhead, correcting capture-budget
regressions, and aligning compound control actions with the system's event-oriented
execution model.

## Scope

### In scope

1. **Render-aware session runtime** — Introduce a per-session runtime/actor that owns
   session wake state, capture cadence, health checks, and render-semantic processing.
   This runtime becomes the canonical owner of live output observation behavior instead
   of a generic fixed-rate polling loop.

2. **Three-lane observability model** — Formalize and preserve the distinct runtime lanes:
   - Hook lane for native authoritative events.
   - Render lane for Codex live semantic inference from rendered tmux snapshots.
   - Transcript lane for discovery, backfill, and post-turn durability.
   The implementation must keep these responsibilities explicit rather than mixing them
   implicitly inside one poll loop, including startup, reconnect, headless-bootstrap,
   and drift-recovery transitions where `pipe-pane` cannot replay prior state.

3. **Wake-driven rendered capture** — Add a dirty/wake signal mechanism so rendered
   snapshots are captured when output likely changed, rather than by blind fixed-rate
   polling alone. `pipe-pane` may be used as the wake signal, but not as the canonical
   semantic source.

4. **Adaptive cadence** — Replace the current steady-state idle polling behavior with
   runtime-managed cadence:
   - fast during active turns, startup, reconnect, and recent user activity,
   - slower during long idle periods,
   - occasional audit snapshots for drift detection and recovery.

5. **Codex semantic preservation** — Preserve the existing live semantic behaviors for
   Codex:
   - synthetic `tool_use`,
   - synthetic `tool_done`,
   - synthetic `user_prompt_submit`,
   while keeping `agent_stop` hook-authoritative.

6. **Capture budget correction** — Split character budget from line lookback so
   `capture-pane` line depth is tuned for terminal semantics rather than reusing the UI
   char budget constant.

7. **Teardown enrichment** — Extend the existing session teardown/cleanup flow so it
   removes per-session temp directories under `~/.teleclaude/tmp/sessions/{session_id}`
   in addition to the resources it already cleans.

8. **Ephemeral control-command lane** — Introduce a queued, non-durable per-session
   control lane for compound actions that may wait on tmux timing, while leaving simple
   single-key controls direct. The control lane may expose queued/dispatched/failed
   feedback, but must not attempt durable replay across daemon restart. Based on the
   current surfaces, the first targets are internal delayed text-injection paths rather
   than the public key-only API.

9. **[inferred] Performance and semantic validation** — Add instrumentation, replay
   fixtures, and validation paths that prove both:
   - lower steady-state tmux overhead,
   - semantic parity for Codex live event synthesis.

10. **Documentation and contract realignment** — Update architecture docs and tests so
    they reflect the real rendered-snapshot model and do not accidentally pin the
    previous hot-loop probe order forever.

### Out of scope

- Replacing tmux as the session substrate.
- Removing transcript discovery/watch behavior for Codex.
- Replacing rendered-state inference with transcript-only or hook-only semantics.
- Changing the canonical event vocabulary exposed to adapters and the TUI.
- Durable replay of ephemeral control commands after daemon restart.
- Reworking plain single-key controls (`enter`, arrows, `tab`, `backspace`, raw
  signals) into a durable receipt system.
- Expanding the public `/sessions/{id}/keys` API into a text-carrying control
  transport as part of this refactor.

## Success Criteria

- [ ] Codex live semantic inference still emits the same effective `tool_use`,
      `tool_done`, and `user_prompt_submit` behavior on replay fixtures and real
      sessions after the runtime refactor.
- [ ] `agent_stop` remains hook-authoritative; the render lane does not synthesize or
      replace stop completion.
- [ ] Idle sessions no longer depend on fixed-rate full rendered snapshots every second
      when no wake signal, turn activity, or audit condition exists.
- [ ] The runtime captures rendered snapshots on meaningful wake/activity transitions
      and still reconciles idle drift with a slower audit path.
- [ ] **[inferred]** Startup, reconnect, headless-bootstrap, and drift-recovery paths
      have explicit lane-authority coverage in docs/tests, with rendered snapshots
      captured anywhere the wake signal cannot reconstruct prior state.
- [ ] **[inferred]** `capture-pane` line lookback and UI char budget are separate
      configuration concerns, and the current regression is removed without silently
      introducing undocumented user-facing config. If new YAML keys, env vars, or
      wizard-visible settings are added, `config.sample.yml`, the config wizard, and
      `docs/project/spec/teleclaude-config.md` are updated in the same change.
- [ ] Session teardown removes per-session temp directories in the existing cleanup
      path.
- [ ] **[inferred]** `get_session_data` transcript/tmux fallback behavior continues to
      work for sessions whose native transcript is not yet available.
- [ ] Durable queued user-message delivery remains unchanged and regression-free.
- [ ] Compound control actions that traverse delayed text+enter injection can return
      queued/dispatched feedback without forcing the caller to wait inline on the
      bridge sleep.
- [ ] **[inferred]** Performance instrumentation records per-session tmux subprocess
      counts and rendered-capture frequency over matched idle observation windows
      before and after the refactor, and the post-change idle measurements are
      strictly lower while the audit path remains observable.
- [ ] Output-polling documentation is updated to describe rendered full-snapshot
      semantics and the Codex render lane accurately.
- [ ] Tests no longer depend on the old assumption that `session_exists()` must run
      before every `capture-pane` call in the hot loop.

## Constraints

- The tmux/subprocess execution model must remain intact so sessions survive daemon
  restart and external runtime continuity is preserved.
- Codex render semantics are derived from rendered tmux state, not raw byte streams.
  Any wake signal mechanism must eventually reconcile through rendered snapshots.
- `pipe-pane -o` attaches prospectively; it does not replay already-rendered pane
  content. Startup, reconnect, and wake attachment therefore still need an explicit
  reconciliation snapshot.
- The runtime must preserve existing adapter contracts and TUI-visible event shapes.
- Health-check and drift-recovery logic must not erase Codex observability guarantees in
  exchange for lower cost.
- The control lane is ephemeral by design. Caller feedback may be evented or receipt-like,
  but not durably replayed after restart.

## Risks

- **Wake signal incompleteness**: `pipe-pane` may not perfectly correspond to every
  semantic boundary the render parser cares about. Mitigation: keep a slower audit
  snapshot path and prove fidelity with replay fixtures and live testing.
- **Parser drift during refactor**: extracting Codex semantic logic out of the current
  poller could change subtle timing or stale-scrollback handling. Mitigation: build a
  fixture corpus and replay the parser before and after the refactor.
- **Boundary confusion**: mixing hook, render, transcript, and control responsibilities
  again would recreate the current ambiguity in a new shape. Mitigation: make the three
  observability lanes and the separate control lane explicit in code structure.
- **Control-lane overreach**: routing simple keys through queued infrastructure would add
  latency for no benefit. Mitigation: keep plain single-key controls direct and move only
  compound/delayed actions.
- **Documentation drift**: current architecture docs describe a simpler diff/cursor
  model and will mislead future work if left unchanged. Mitigation: update docs as part
  of the runtime refactor, not as an afterthought.
- **Test ossification**: some current tests lock in the exact hot-loop probe order
  instead of the real behavior contract. Mitigation: rewrite those tests around
  semantic/output invariants before or alongside the refactor.
