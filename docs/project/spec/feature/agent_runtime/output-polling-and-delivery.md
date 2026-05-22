---
id: 'project/spec/feature/agent_runtime/output-polling-and-delivery'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Daemon-internal per-session polling + transcript projection that detects new agent output, dedups via digest, and delivers via adapters.'
---

# Output Polling and Delivery — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The v1 output-polling-and-delivery substrate is a daemon-internal, per-session background machinery that observes a running agent's tmux pane and hook activity for liveness, consumes the agent CLI's native transcript file as the source of truth for content, projects new turns into structured outbound messages, and delivers them through the `AdapterClient` to subscribed adapters (Telegram, Discord, web, terminal). It is composed of three cooperating pieces inside `teleclaude.core.polling_coordinator`:

1. **Polling registration** (`schedule_polling` → `poll_and_send_output`) — one background asyncio task per session, gated by an in-memory `_active_pollers` set under `_poller_lock` so a session never has two concurrent pollers.
2. **Transcript-driven projection** (`project_session_from_transcript` + `_build_transcript_output_update` + `_project_user_reflection`) — when the underlying `OutputPoller` signals `OutputChanged`, the coordinator reads the agent's native transcript, derives the current-turn render, and dedups against `last_projected_output_digest` before handing off to the adapter.
3. **Scheduled session projection** (`schedule_session_projection`) — a hook/activity wakeup pathway for all session lifecycle states. Pending-signal coalescing under `_session_projection_signal_lock` guarantees overlapping triggers fold into a single re-run, and `schedule_headless_projection` remains a thin wrapper that passes `headless_only=True`.

Distinct from this lane: the on-demand transcript retrieval surface (`GET /sessions/{id}/messages`, which projects on request from the same transcript) and the v2 hook + render lanes (planned). v1 polling is liveness-driven push, not request-driven pull, and tmux is treated strictly as a _signal_ — content always comes from the transcript file.

## Canonical fields

### Behavioral contract

#### Per-session polling registration

```
Given a session has a tmux_session_name and an active agent
When the daemon calls polling_coordinator.schedule_polling
Then _register_polling atomically inserts the session_id into _active_pollers under _poller_lock
And returns True on first registration / False if already polling
And on True a background asyncio task named "poll-output-<session_id>" is created running poll_and_send_output
And on False the call logs a "Polling already active" warning and returns without scheduling
```

```
Given polling for a session is already active
When schedule_polling is invoked again for the same session_id
Then no second task is created
And the call is a no-op returning False
```

#### Tmux liveness signal vs. transcript truth

```
Given poll_and_send_output is consuming events from OutputPoller.poll
When an OutputChanged event arrives
Then the coordinator fetches the latest Session row from db
And updates last_activity
And calls project_session_from_transcript with started_at and last_changed_at from the event
And the OutputChanged.output payload is NOT delivered as content — it is treated as a liveness signal only
```

```
Given any supported agent CLI
And the Session has no native_log_file yet
When OutputChanged fires
Then _try_bind_transcript_path attempts to discover the native transcript path from active_agent + native_session_id
And on success updates the Session row with the discovered native_log_file
And on miss leaves the session eligible for a later retry because transcript files can land after early signals
```

#### Hook/activity projection signals

```
Given AgentCoordinator handles user_prompt_submit
When origin metadata and last_activity have been persisted
Then schedule_session_projection is invoked for active sessions
And schedule_session_projection(..., headless_only=True) is invoked for headless sessions
And projection still reads transcript/source truth before delivering any content
```

```
Given AgentCoordinator handles tool_use
When activity/status metadata has been emitted and first-tool timing has been recorded if needed
Then _signal_projection_activity schedules a transcript projection pass for active sessions
And _signal_projection_activity preserves the headless_only guard for headless sessions
And the tool hook is treated as a liveness signal, not as delivered content
```

```
Given AgentCoordinator handles agent_stop
When completed status has been emitted
Then _signal_projection_activity schedules an immediate transcript projection pass before stop finalization
And slow summary/title/TTS work remains separate from transcript projection
```

```
Given daemon_hook_outbox handles NATIVE_METADATA_UPDATE or NATIVE_SESSION_REFRESH
When the session-row mutation has been persisted
Then schedule_session_projection is invoked for active sessions
And schedule_session_projection(..., headless_only=True) is invoked for headless sessions
And the dispatch path returns without routing a synthetic AGENT_EVENT
```

#### Transcript-based change detection

```
Given a session with a native_log_file and an active_agent
When _build_transcript_output_update runs
Then it extracts the start-of-current-turn anchor via extract_last_turn_boundary_timestamp
And reads the assistant messages since that anchor via get_assistant_messages_since
And returns None when no assistant messages exist since the anchor
And otherwise renders the cumulative current-turn view:
  - multi-block turns use render_agent_output (includes tool calls, excludes tool results)
  - single-block turns use render_clean_agent_output
And returns (message, last_ts, is_multi)
```

```
Given the active_agent value is not a known AgentName
When _build_transcript_output_update tries AgentName.from_str
Then it logs "Invalid active_agent" and returns None — no projection happens
```

#### Digest-based output dedup

```
Given project_session_from_transcript has built a transcript update (message, last_ts, is_multi)
When _output_projection_digest is computed
Then it is a SHA-256 of the joined tuple (last_ts ISO UTC, "multi"|"single", message)
And if session.last_projected_output_digest equals the new digest
Then adapter delivery is SKIPPED and the session is returned unchanged
And only when the digest differs does adapter_client.send_output_update fire
And on successful delivery the Session row's last_projected_output_digest is updated to the new value
```

#### User-reflection projection (input-echo)

```
Given a session whose transcript carries a fresh user turn
When _project_user_reflection runs (invoked before output projection)
Then it extracts the last user message + timestamp via extract_last_user_message_with_timestamp
And dedups against the projection watermark session.last_projected_at (NOT last_message_sent_at)
And gates on has_fresh_origin_for_user — only when last_input_origin matches the current unprojected user turn does it proceed
And broadcasts the user input via adapter_client.broadcast_user_input UNLESS the origin is DISCORD (origin-side delivery already covered the Discord audience)
And updates last_message_sent, last_message_sent_at, last_projected_at on the Session row
And signals can_project_output=True when the user reflection step is complete (or no-op)
And signals can_project_output=False when the origin is not yet fresh, deferring output projection to a later signal
```

#### Output cadence metrics

```
Given an output update was delivered for a session
When _record_output_tick runs
Then it appends the (now - last_tick_at) interval to OutputMetricsState.cadence_samples_s
And increments ticks and fanout_chars (output length)
And every OUTPUT_METRICS_SUMMARY_INTERVAL_S (30s) emits an "Output cadence summary" log with avg_cadence_s and p95_cadence_s
And resets ticks / fanout_chars / cadence_samples_s after each periodic summary
```

```
Given a session's polling task terminates (normal exit, cancellation, or error)
When poll_and_send_output enters its finally block
Then _clear_output_metrics emits one final "Output cadence summary" with reason="final"
And clears the per-session OutputMetricsState entry
And clears the title projection state via clear_title_projection_state
```

#### Scheduled session projection coalescing

```
Given schedule_session_projection is invoked for any session
When no scheduled projection task is already active for that session
Then _register_session_projection inserts the session_id into _active_session_projections under _session_projection_signal_lock
And the caller starts an asyncio task named "project-session-<session_id>" or "project-headless-<session_id>" running _run()
```

```
Given a scheduled projection task is already in flight for a session
When a second schedule_session_projection arrives
Then _register_session_projection adds the session_id to _pending_session_projections and returns False
And the caller does NOT start a new task
And when the running task completes its current pass, _consume_pending_projection observes the pending flag and loops once more on the configured projection cadence
And this guarantees state changes that land during a projection (e.g. session title update) are folded into the next pass without needing a fresh external signal
```

```
Given a scheduled projection task is ready to project
When _wait_for_session_projection_cadence runs
Then it enforces config.polling.output_cadence_s as the per-session floor between scheduled projection starts
And digest dedupe still decides whether the adapter sees any outbound update
```

```
Given headless_only=True is in effect
When _run reloads the session at the top of each loop iteration
Then if the session has disappeared OR its lifecycle_status is no longer "headless" the loop exits and the slot is released
```

```
Given any exception escapes _run
When the finally clause executes
Then _release_session_projection drops both the active and pending entries unconditionally
And subsequent signals will be able to schedule a fresh task
```

#### Process-exit / tmux-death handling

```
Given OutputPoller yields ProcessExited(exit_code=<int>)
When poll_and_send_output handles it
Then it updates last_activity
And checks tmux_bridge.session_exists for the session's tmux_session_name
And if the tmux session is gone, calls session_cleanup.terminate_session with reason="tmux_exited" and kill_tmux=False
And logs "Terminated session ... after tmux exit"
And if the tmux session is still alive, logs that polling stopped but keeps the output file for downloads (no termination)
```

```
Given OutputPoller yields ProcessExited(exit_code=None)
When poll_and_send_output handles it
Then it logs "Tmux session missing for ...; polling stopped without recovery"
And does NOT attempt background healing — recovery is demand-driven by subsequent caller actions
```

#### Polling task teardown

```
Given poll_and_send_output exits the poll() async iteration for any reason
When the finally block runs
Then _unregister_polling removes the session_id from _active_pollers under _poller_lock
And _cleanup_codex_input_state drops the transcript-bind attempt record
And _clear_output_metrics emits the final cadence summary and drops the metrics and scheduled-projection cadence state
And a final debug log "Polling ended for session ..." is emitted
And subsequent schedule_polling calls for the same session_id are once again eligible
```

```
Given the polling task crashes with an unexpected exception
When the except clause in poll_and_send_output runs
Then adapter_client.send_error_feedback is invoked with "Polling error: <exc>"
And the exception is re-raised so the asyncio task callback (_handle_background_poller_result) can log it
And the finally block still tears down state cleanly
```

### Implementation pointers (v1)

- `teleclaude/core/polling_coordinator.py:550` — `schedule_polling` (registration + task spawn).
- `teleclaude/core/polling_coordinator.py:581` — `poll_and_send_output` (OutputPoller event loop; transcript projection per OutputChanged; ProcessExited handling; finally-block teardown).
- `teleclaude/core/polling_coordinator.py:475` — `project_session_from_transcript` (user reflection → output projection orchestrator with digest dedup).
- `teleclaude/core/polling_coordinator.py:70` — `_build_transcript_output_update` (turn-anchor read, multi-vs-single render selection).
- `teleclaude/core/polling_coordinator.py:372` — `_project_user_reflection` (user-turn broadcast + watermark advance).
- `teleclaude/core/polling_coordinator.py:267` — `_output_projection_digest` (SHA-256 dedup key).
- `teleclaude/core/polling_coordinator.py:193` — `_try_bind_transcript_path` (generic native transcript binding).
- `teleclaude/core/polling_coordinator.py:496` — `schedule_session_projection` (general projection scheduler with pending coalescing).
- `teleclaude/core/polling_coordinator.py:545` — `schedule_headless_projection` (thin wrapper enforcing `headless_only=True`).
- `teleclaude/core/polling_coordinator.py:314` — `_wait_for_session_projection_cadence` (scheduled projection cadence floor).
- `teleclaude/core/polling_coordinator.py:287` — `_register_polling` / `_unregister_polling` (poll-lock guards).
- `teleclaude/core/polling_coordinator.py:330` — `_register_session_projection` / `_consume_pending_projection` / `_release_session_projection` (scheduled projection guards).
- `teleclaude/core/polling_coordinator.py:47` — `OutputMetricsState` dataclass.
- `teleclaude/core/polling_coordinator.py:40` — `OUTPUT_METRICS_SUMMARY_INTERVAL_S` constant (30s).
- `teleclaude/core/polling_coordinator.py:249` — `has_fresh_origin_for_user` (origin-vs-watermark gate).
- `teleclaude/core/output_poller.py:51` — `OutputPoller` (tmux pane snapshot loop yielding `OutputChanged` / `ProcessExited`).
- `teleclaude/core/output_poller.py:253` — `OutputPoller.poll` (cadence + idle-flush logic; default `output_cadence_s=1.0` from `config.polling.output_cadence_s`).
- `teleclaude/daemon.py:918` — `_poll_and_send_output` wrapper that calls `schedule_polling`.
- `teleclaude/daemon.py:932` — `_ensure_output_polling` (skip if already polling; require live tmux).
- `teleclaude/daemon.py:944` — `_start_polling_for_session` (entry point passed to `command_service` as `start_polling`).
- `teleclaude/core/agent_coordinator/_coordinator.py:107` — `_signal_projection_activity` (hook/activity entry into scheduled projection).
- `teleclaude/core/agent_coordinator/_coordinator.py:429` — `user_prompt_submit` scheduled projection call site.
- `teleclaude/core/agent_coordinator/_coordinator.py:485` — `agent_stop` scheduled projection call site.
- `teleclaude/core/agent_coordinator/_coordinator.py:653` — `tool_use` scheduled projection call site.
- `teleclaude/daemon_hook_outbox.py:131` — `_schedule_projection_from_signal` (native metadata/session-refresh entry into scheduled projection).
- `docs/project/design/architecture/output-polling.md`, `docs/project/design/architecture/output-delivery.md` — v1 design intent.

### Cross-context references

- **integration** — `AdapterClient.send_output_update` and `broadcast_user_input` deliver the projected messages to adapter-bound subscribers (Telegram, Discord, web, terminal). Adapter-side fanout, edit-vs-append semantics, and chunking are integration's concern. agent_runtime hands over a fully rendered `(message, delivery_ts, multi_message)` triple and lets integration decide how it lands.
- **session_mirrors** — consumes the SAME native transcript as agent_runtime, but at session-end (eternal extract) rather than per-turn. Same source, different consumer; no shared state. session_mirrors must not assume agent_runtime has projected every turn — only that the transcript file is complete at end.
- **identity** — `InputOrigin` (used by `has_fresh_origin_for_user`) and the `last_input_origin` Session field originate in identity. The Discord-skip rule in `_project_user_reflection` is an identity-domain policy applied by agent_runtime when projecting user turns.
- **config** — `config.polling.output_cadence_s` (default `1.0`) drives the `OutputPoller` cadence floor; `OUTPUT_METRICS_SUMMARY_INTERVAL_S` (30s) is a coordinator-internal constant. Polling-related knobs live in config's `polling` section.

## Known caveats

- **Tmux is liveness, transcript is truth.** `OutputChanged.output` from the tmux poller is intentionally discarded — never used as content. All delivered content comes from re-reading the agent's native transcript via the start-of-turn anchor. Don't add code that forwards `OutputChanged.output` to the adapter.
- **Cumulative-turn projection, not incremental.** Each tick renders the _entire_ current turn from the start-of-turn anchor forward. Adapters use the digest to decide whether to edit, and integration handles append-vs-edit semantics. The coordinator does not produce diffs.
- **`last_message_sent_at` is mixed-purpose.** The projection watermark deliberately uses `last_projected_at` instead, because `last_message_sent_at` is touched by multiple writers and would cause projection skips or re-broadcasts. Don't conflate them.
- **Transcript binding retries until success.** If discovery misses because the transcript file has not landed yet, the session remains eligible for later poller or hook-triggered discovery. Only a successful bind records the session_id in `_transcript_bind_attempted`.
- **Scheduled projection coalesces N signals into ≤1 re-run.** If 10 events arrive while a projection is running, exactly one extra pass executes when it finishes — not 10. Callers that need every signal observed individually must not use scheduled projection as an event log.
- **Polling stops, the file remains.** When tmux survives but the agent process exits cleanly (`ProcessExited(exit_code=int)`), polling stops, the session is NOT terminated, and the transcript stays on disk for downloads. The next subscriber action drives recovery.
- **No durable replay.** If the daemon restarts while a session is mid-turn, the transcript-based digest dedup will re-emit the current turn on next projection (digest mismatch against empty / stale state). Edit-based adapters absorb this; append-based adapters may see duplicate content.
- **`output_cadence_s` governs both tmux polling and scheduled projection wakeups.** The poller wakes at most every `min(1.0, output_cadence_s)` seconds; scheduled projection also uses `output_cadence_s` as a per-session floor between projection starts. Digest dedupe still decides whether a wakeup produces outbound adapter work.
- **Metrics state survives only inside the polling task.** `_output_metrics_state` is a module-level dict keyed by session_id; restart loses the running averages but emits a final summary before clearing on task teardown.
