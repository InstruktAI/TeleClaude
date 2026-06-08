---
id: 'project/spec/feature/agent_runtime/output-polling-and-delivery'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'agent_runtime-internal per-session polling + transcript projection that detects new agent output, dedups via digest, and delivers via adapters.'
---

# Output Polling and Delivery — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

Output-polling-and-delivery is an agent_runtime-internal, per-session background machinery that observes a running agent's host pane and hook activity for liveness, consumes the agent CLI's native transcript file as the source of truth for content, projects new turns into structured outbound messages, and delivers them through the adapter client to subscribed adapters (Telegram, Discord, web, terminal). It is composed of three cooperating pieces inside the polling coordinator:

1. **Polling registration** — one background polling task per session, gated by an in-memory active-poller set under a coordinator lock so a session never has two concurrent pollers.
2. **Transcript-driven projection** — when the underlying pane poller signals "output changed," the coordinator reads the agent's native transcript, derives the current-turn render, and dedups against the per-session projection digest before handing off to the adapter client.
3. **Scheduled session projection** — a hook/activity wakeup pathway for all session lifecycle states. Pending-signal coalescing under a coordinator lock guarantees overlapping triggers fold into a single re-run, and a headless-only variant scopes projections to headless sessions.

Distinct from this lane: the on-demand transcript retrieval surface (which projects on request from the same transcript) and the v2 hook + render lanes (planned). v1 polling is liveness-driven push, not request-driven pull, and the host pane is treated strictly as a _signal_ — content always comes from the transcript file.

## Canonical fields

### Behavioral contract

#### Per-session polling registration

```
Given a session has a bound host pane and an active agent
When the agent_runtime service asks the polling coordinator to schedule polling
Then the coordinator atomically inserts the session id into the active-poller set under its registration lock
And returns true on first registration / false if already polling
And on true a background polling task is created
And on false the call logs a "polling already active" warning and returns without scheduling
```

```
Given polling for a session is already active
When schedule-polling is invoked again for the same session id
Then no second task is created
And the call is a no-op returning false
```

#### Host-pane liveness signal vs. transcript truth

```
Given the polling task is consuming events from the pane output poller
When an "output changed" event arrives
Then the coordinator fetches the latest session row from storage
And updates last-activity
And calls project-session-from-transcript with the timing markers from the event
And the output payload reported by the pane poller is NOT delivered as content — it is treated as a liveness signal only
```

```
Given any supported agent CLI
And the session has no recorded native transcript file yet
When the output-changed signal fires
Then the coordinator attempts to discover the native transcript path from the active agent plus native session id
And on success updates the session row with the discovered native transcript file path
And on miss leaves the session eligible for a later retry because transcript files can land after early signals
```

#### Hook/activity projection signals

```
Given the agent coordinator handles a user-prompt-submit event
When origin metadata and last-activity have been persisted
Then a transcript projection is scheduled for active sessions
And a headless-only transcript projection is scheduled for headless sessions
And projection still reads transcript truth before delivering any content
```

```
Given the agent coordinator handles a tool-use event
When activity/status metadata has been emitted and first-tool timing has been recorded if needed
Then projection-activity signaling schedules a transcript projection pass for active sessions
And the headless-only guard is preserved for headless sessions
And the tool hook is treated as a liveness signal, not as delivered content
```

```
Given the agent coordinator handles an agent-stop event
When the completed status has been emitted
Then projection-activity signaling schedules an immediate transcript projection pass before stop finalization
And slow summary/title/TTS work remains separate from transcript projection
```

```
Given the hook outbox handles a native-metadata-update or native-session-refresh signal
When the session-row mutation has been persisted
Then a transcript projection is scheduled for active sessions
And a headless-only transcript projection is scheduled for headless sessions
And the dispatch path returns without routing a synthetic agent event
```

#### Transcript-based change detection

```
Given a session with a recorded native transcript file and an active agent
When the transcript-update builder runs
Then it extracts the start-of-current-turn anchor from the transcript
And reads the assistant messages since that anchor
And returns nothing when no assistant messages exist since the anchor
And otherwise renders the cumulative current-turn view:
  - multi-block turns use the multi-block renderer (includes tool calls, excludes tool results)
  - single-block turns use the clean single-block renderer
And returns the rendered message, the last timestamp seen, and whether the turn is multi-block
```

```
Given the active-agent value is not a known agent name
When the transcript-update builder tries to resolve the agent
Then it logs an "invalid active agent" warning and returns nothing — no projection happens
```

#### Digest-based output dedup

```
Given the transcript projection has built an update (message, last timestamp, multi-block flag)
When the projection digest is computed
Then it is a SHA-256 of the joined tuple (last timestamp in ISO UTC, "multi"|"single", message)
And if the session's recorded projection digest equals the new digest
Then adapter delivery is SKIPPED and the session is returned unchanged
And only when the digest differs does the adapter client fire its send-output-update path
And on successful delivery the session row's projection digest is updated to the new value
```

#### User-reflection projection (input-echo)

```
Given a session whose transcript carries a fresh user turn
When the user-reflection step runs (invoked before output projection)
Then it extracts the last user message and its timestamp
And dedups against the projection watermark (last-projected-at; NOT last-message-sent-at)
And gates on a fresh-origin check — only when the recorded last-input-origin matches the current unprojected user turn does it proceed
And broadcasts the user input via the adapter client UNLESS the origin is Discord (origin-side delivery already covered the Discord audience)
And updates last-message-sent, last-message-sent-at, and last-projected-at on the session row
And signals that output projection may proceed when the user-reflection step is complete (or no-op)
And signals that output projection should defer when the origin is not yet fresh
```

<!-- planned:suppress-command-body-in-projection -->
#### UC-OPD1: Command-body expansion with ADDITIONAL CONTEXT projects as title plus that section, never the body

```
Given a user turn that is a slash-command expansion wrapped in command-message tags, carrying the full procedure body and an appended "ADDITIONAL CONTEXT:" section
When that user turn is extracted for projection
Then the projected text is the command title line followed by the ADDITIONAL CONTEXT section verbatim
And the procedure body does not appear in the projected text
```

#### UC-OPD2: Command-body expansion without ADDITIONAL CONTEXT projects as the title line only

```
Given a user turn that is a slash-command expansion wrapped in command-message tags, carrying the full procedure body and no ADDITIONAL CONTEXT section
When that user turn is extracted for projection
Then the projected text is the command title line only
And the procedure body does not appear in the projected text
```

#### UC-OPD3: A non-command user turn is projected unchanged

```
Given a user turn whose text is ordinary content with no command-message wrapper
When that user turn is extracted for projection
Then the projected text equals the original user text
```
<!-- /planned:suppress-command-body-in-projection -->

#### Output cadence metrics

```
Given an output update was delivered for a session
When the output-tick recorder runs
Then it appends the interval since the previous tick to the cadence samples
And increments the per-session tick count and fan-out character count
And every configured summary interval (default 30s) emits an "output cadence summary" log with average and p95 cadence
And resets ticks / fan-out / cadence samples after each periodic summary
```

```
Given a session's polling task terminates (normal exit, cancellation, or error)
When the polling task enters its finalizer
Then the cadence summary is emitted one final time with reason "final"
And the per-session metrics state is cleared
And the title projection state is cleared
```

#### Scheduled session projection coalescing

```
Given a scheduled projection is requested for any session
When no scheduled projection task is already active for that session
Then the session id is inserted into the active projections set under the projection-signal lock
And the caller starts a scheduled projection task
```

```
Given a scheduled projection task is already in flight for a session
When a second projection request arrives
Then the session id is added to the pending set and the request returns without starting a new task
And when the running task completes its current pass, the pending flag is observed and the task loops once more on the configured projection cadence
And this guarantees state changes that land during a projection (e.g., session title update) are folded into the next pass without needing a fresh external signal
```

```
Given a scheduled projection task is ready to project
When the cadence-floor wait runs
Then it enforces the configured per-session floor between scheduled projection starts
And digest dedup still decides whether the adapter sees any outbound update
```

```
Given a headless-only projection is in effect
When the scheduled projection task reloads the session at the top of each loop iteration
Then if the session has disappeared OR its lifecycle status is no longer headless, the loop exits and the slot is released
```

```
Given any exception escapes the scheduled projection task
When the finalizer executes
Then the active and pending entries are dropped unconditionally
And subsequent signals will be able to schedule a fresh task
```

#### Process-exit / host-pane-death handling

```
Given the pane output poller signals process-exited with a numeric exit code
When the polling task handles it
Then it updates last-activity
And checks whether the recorded host pane still exists
And if the host pane is gone, runs session termination with reason "host pane exited" and host-pane kill suppressed (already gone)
And logs the termination
And if the host pane is still alive, logs that polling stopped but keeps the output file for downloads (no termination)
```

```
Given the pane output poller signals process-exited with no exit code (host pane vanished)
When the polling task handles it
Then it logs that the host pane is missing and polling stopped without recovery
And does NOT attempt background healing — recovery is demand-driven by subsequent caller actions
```

#### Polling task teardown

```
Given the polling task exits its event loop for any reason
When the finalizer runs
Then the session id is removed from the active-poller set under the registration lock
And per-session input-state state is dropped
And a final cadence summary is emitted and per-session metrics and scheduled-projection cadence state are cleared
And a final teardown log is emitted
And subsequent schedule-polling calls for the same session id are once again eligible
```

```
Given the polling task crashes with an unexpected exception
When the except clause in the polling task runs
Then the adapter client is asked to send error feedback with the message
And the exception is re-raised so the background-task callback can log it
And the finalizer still tears down state cleanly
```

### Cross-context references

- **integration** — the adapter client's send-output-update and broadcast-user-input paths deliver the projected messages to adapter-bound subscribers (Telegram, Discord, web, terminal). Adapter-side fanout, edit-vs-append semantics, and chunking are integration's concern. agent_runtime hands over a fully rendered (message, delivery timestamp, multi-message flag) triple and lets integration decide how it lands.
- **session_mirrors** — consumes the SAME native transcript as agent_runtime, but at session-end (eternal extract) rather than per-turn. Same source, different consumer; no shared state. session_mirrors must not assume agent_runtime has projected every turn — only that the transcript file is complete at end.
- **identity** — the input-origin concept (used by the fresh-origin gate) and the last-input-origin field on the session originate in identity. The Discord-skip rule in the user-reflection step is an identity-domain policy applied by agent_runtime when projecting user turns.
- **config** — the configured output cadence (default 1.0s) drives the pane-poller cadence floor; the metrics summary interval (30s) is a coordinator-internal constant. Polling-related knobs live in the configuration's polling section.

## Known caveats

- **Host pane is liveness, transcript is truth.** The output payload reported by the pane poller is intentionally discarded — never used as content. All delivered content comes from re-reading the agent's native transcript via the start-of-turn anchor. Don't add code that forwards pane-poller output to the adapter.
- **Cumulative-turn projection, not incremental.** Each tick renders the _entire_ current turn from the start-of-turn anchor forward. Adapters use the digest to decide whether to edit, and integration handles append-vs-edit semantics. The coordinator does not produce diffs.
- **`last-message-sent-at` is mixed-purpose.** The projection watermark deliberately uses `last-projected-at` instead, because `last-message-sent-at` is touched by multiple writers and would cause projection skips or re-broadcasts. Don't conflate them.
- **Transcript binding retries until success.** If discovery misses because the transcript file has not landed yet, the session remains eligible for later poller or hook-triggered discovery. Only a successful bind records the session id as bound.
- **Scheduled projection coalesces N signals into <=1 re-run.** If 10 events arrive while a projection is running, exactly one extra pass executes when it finishes — not 10. Callers that need every signal observed individually must not use scheduled projection as an event log.
- **Polling stops, the file remains.** When the host pane survives but the agent process exits cleanly, polling stops, the session is NOT terminated, and the transcript stays on disk for downloads. The next subscriber action drives recovery.
- **No durable replay.** If the agent_runtime service restarts while a session is mid-turn, the transcript-based digest dedup will re-emit the current turn on next projection (digest mismatch against empty / stale state). Edit-based adapters absorb this; append-based adapters may see duplicate content.
- **Output cadence governs both host-pane polling and scheduled projection wakeups.** The pane poller wakes at most every min(1.0, configured cadence) seconds; scheduled projection also uses the configured cadence as a per-session floor between projection starts. Digest dedup still decides whether a wakeup produces outbound adapter work.
- **Metrics state survives only inside the polling task.** Metrics state is keyed by session id; restart loses the running averages but emits a final summary before clearing on task teardown.
