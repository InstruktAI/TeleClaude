# Input: session-runtime-overhaul

We want the best long-term architecture for session runtime observability and control,
not a local micro-optimization that preserves the current shape forever.

Important constraints and agreements:

- The tmux/subprocess session model stays. Sessions must survive daemon restarts so
  music and long-running agent activity continue.
- Codex live observability depends on rendered tmux output, not just hooks or
  transcript files. The current system synthesizes live `tool_use`, `tool_done`,
  and `user_prompt_submit` effects from visible terminal state.
- `agent_stop` remains hook-authoritative. The render lane must not replace that.
- Transcript discovery and transcript parsing remain important for durability,
  backfill, and post-turn access, but they are not the canonical source for live
  Codex turn semantics.
- Raw `pipe-pane` output is not enough by itself because the semantic parser
  depends on the rendered screen state that `capture-pane` exposes.
- The idle poller is too expensive in its current form. Reducing cost by just
  offloading the same tmux subprocess work to another worker is not a real fix.
- The `capture-pane` regression must be corrected: character budget and line
  lookback must be separate concepts.
- Per-session temp directories under `~/.teleclaude/tmp/sessions/{session_id}`
  should be removed during the existing teardown path, not by inventing a second
  cleanup system.
- The one-second delay before text+enter injection is acceptable for correctness,
  but caller-facing paths that do not need to block on it should not wait inline.

Current problem areas:

1. Session teardown does not remove per-session temp directories, so they accumulate.
2. The output poller does repeated tmux probes on idle sessions even when nothing
   meaningful changed.
3. `capture-pane` currently uses a char-budget constant as if it were a line count.
4. Compound control actions that rely on delayed text+enter injection still have
   an inline execution model in some caller paths.

Agreed architecture direction:

1. Keep `capture-pane` as the canonical live semantic source for Codex rendered-state
   inference.
2. Introduce a dedicated render-aware session runtime / actor per active session.
3. Split runtime signals into three lanes:
   - Hook lane: authoritative where native hooks exist.
   - Render lane: authoritative for Codex live semantic inference from tmux snapshots.
   - Transcript lane: durable reconciliation/backfill, not live authority.
4. Use `pipe-pane` only as a wake / dirty signal that tells the runtime when a
   new rendered snapshot should be captured.
5. Replace fixed-rate blind polling with adaptive cadence:
   - fast while a turn is active or a session was recently poked,
   - slow while idle,
   - occasional audit/reconciliation snapshots.
6. Keep durable queue-backed user message delivery as-is.
7. Introduce an ephemeral per-session command lane for compound control actions
   that can safely return queued/dispatched status without blocking on tmux timing.
   Plain single-key controls remain direct.

Evidence gathered on 2026-03-08:

1. Live Codex semantics are currently computed inline in the generic polling path.
   `poll_and_send_output()` runs `_maybe_emit_codex_turn_events()` and
   `_maybe_emit_codex_input()` on every `OutputChanged` event before adapter fanout.
   The live parser depends on:
   - prompt visibility near the live bottom,
   - short live status/spinner markers,
   - compact dimmed assistant boundary lines,
   - visible action-word lines with signature suppression,
   - stale scrollback rejection,
   - authoritative prompt seeding from durable message dispatch.
   `agent_stop` remains hook-authoritative, while transcript extraction in
   `handle_agent_stop()` backfills missing Codex submit context only as a safety net.

2. Existing test coverage protects many parser invariants already.
   `tests/unit/test_polling_coordinator.py` covers partial prompt typing, stale bullet
   rejection, compact dimmed boundaries, prompt-to-agent transition emits, prompt
   seeding, stale scrollback suppression, tool preview extraction, tool signature
   suppression, and "no synthetic agent_stop" behavior. This means the refactor can
   move code, but it cannot casually change parser semantics.

3. There is still no real Codex replay corpus.
   `tests/fixtures/transcripts/` currently contains Gemini transcript fixtures only,
   and `tests/snapshots/` is TUI-focused. The Codex semantic parser is tested with
   synthetic inline strings, not captured real pane snapshots from startup, reconnect,
   tool-heavy turns, interrupts, or compact fast-turn states.

4. Local `pipe-pane` probes support the wake-signal idea, but only as a wake signal.
   On tmux 3.5a, an isolated probe session showed:
   - `pipe-pane -o` attached prospectively; it did not replay already-rendered prompt
     content when attached after shell startup,
   - new output bytes included command echo, prompt redraw, bracketed-paste mode
     toggles, and carriage-return in-place updates,
   - the stream is clearly suitable for "something changed" detection,
     but it is not a substitute for rendered-screen snapshots.

5. The control-lane scope is narrower than first assumed.
   Durable user text already flows through the inbound queue, so the one-second
   text+enter sleep is already off the normal caller path for `/message`.
   The public `/sessions/{id}/keys` API and `TelecAPIClient.send_keys()` expose only
   `key` plus optional `count`; plain keys are already direct. The first worthwhile
   queued control targets are therefore internal delayed text-injection paths and any
   future compound controls, not the current key-only API surface.

6. Baseline numbers confirm the problem is operational, not theoretical.
   Current local state:
   - `polling.output_cadence_s` default is `1.0`
   - `DIRECTORY_CHECK_INTERVAL = 5`
   - `UI_MESSAGE_MAX_CHARS = 3900`
   - `CODEX_TOOL_ACTION_LOOKBACK_LINES = 120`
   - `CODEX_PROMPT_LIVE_DISTANCE = 4`
   - `27` live `tc_` tmux sessions
   - database lifecycle rows: `15` active, `12` closing, `2` initializing
   - active-agent split among non-closed rows: `10` active Claude, `5` active Codex
   - `1932` temp-session directories under `~/.teleclaude/tmp/sessions`
   Recent logs also show active Codex pollers commonly running near ~1.06-1.50s
   output cadence with large fanout volumes, and monitoring snapshots show fd/task
   spikes during activity.

7. Documentation and tests currently overfit the old poller shape.
   `docs/project/design/architecture/output-polling.md` still describes a simpler
   diff/cursor-oriented model and does not mention the Codex render-semantic lane.
   `tests/unit/test_output_poller.py` also contains assertions that lock in the current
   hot-loop probe order, such as `session_exists()` running before each capture. A
   runtime refactor will need explicit doc and test updates, not just code changes.

What I still want to know before implementation:

1. Exact live dependency surface at reconnect and drift boundaries: the main parser
   invariants are now mapped, but reconnect/startup/headless-bootstrap cases still
   need a more explicit authority table.
2. Real-world output patterns: a replay corpus of captured Codex pane snapshots across
   models, themes, fast turns, tool-heavy turns, interrupts, startup, and reconnect.
3. Wake fidelity under lifecycle churn: attach/detach behavior, missed bytes,
   slow-output turns, and whether a low-frequency audit path is enough to recover.
4. Control-lane boundaries beyond the current key-only API: which internal delayed
   text injection paths should move first, and whether any other compound controls
   exist outside `escape` with args and normal text delivery.
5. Performance baseline at tmux-call granularity: current logs show fanout cadence and
   resource pressure, but not exact per-session `tmux` subprocess counts or capture
   sizes. That still needs explicit instrumentation or sampling.
