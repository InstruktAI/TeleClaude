---
id: project/spec/domain/agent_runtime
type: spec
domain: software-development
scope: project
visibility: public
status: target
delivered_by:
  - v2-agent-runtime
description: Agent Runtime bounded context — live agent sessions, tmux orchestration,
  agent CLI supervision, three-lane signal architecture. The heart of v2 — the genuine
  daemon-shaped part of the platform.
---

# Agent Runtime Domain Spec — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md

## What it is

The `agent_runtime` bounded context owns LIVE agent sessions — the tmux processes, the supervised agent CLIs (Claude, Codex, Gemini), the input/output streaming, the moment-by-moment session state. It binds an `agent` (a process) to a `principal` (an identity) and tracks lifecycle from start to end.

Three signal lanes (hook, render, transcript) coordinate the live state — each lane authoritative for what it owns; never replacing each other. A per-session `SessionRuntime` actor holds state, an adaptive cadence state machine throttles tmux probes, and an ephemeral control queue routes compound interactions that would otherwise block the caller.

This context is the genuine daemon-shaped part of the platform. The `telec-daemon` binary embeds it in long-running form. CLI and TUI also embed for read queries. The cutover from v1 to v2 IS the daemon swap — there's no separate `v2-agent-runtime-cutover`.

This context does NOT own: local project bookkeeping (`workflow`), historical text-only mirrors (`session_mirrors`), knowledge storage (`knowledge`), UI/business logic.

This context DOES own agent CLI hook reception: the `telec-hook` binary, the hook receiver, and the windowed-batch-write mechanism that processes incoming hook events. Per `transport-rules.md` (change-axis test), agent CLI hooks belong here because the agent CLI is a system we control (supervise, deploy, configure) — not an external system. Truly external inputs (HTTP webhooks from Telegram, GitHub, etc.) remain `integration`'s domain.

The runtime ledger (the `sessions` Postgres table this context owns) is operational. It is pruned after a short window (~1-2 weeks). The durable historical record is the mirror in `session_mirrors`, which is eternal and independent. Native session transcript files (owned by the agent CLIs themselves) are the ground truth that both contexts reference; agent_runtime stores the path for live operations, session_mirrors extracts the text at session-end for permanent search.

## Canonical fields

### Ubiquitous language

**Session** (per glossary — live dimension)
: A unit of agent work in progress. Has a tmux name, native session id, principal binding, status, last activity, project path, additional context. The thing humans see in the session list.

**Session id**
: UUID identifying the session. Shared with `session_mirrors` (same id, different lens). The wire identifier in events.

**TeleClaude session id**
: Same as session_id. Used in cross-context contexts where "session id" alone might be ambiguous.

**Native session id**
: The agent CLI's internal session identifier. Different per agent: Claude has one format, Codex another, Gemini another. Stored explicitly to enable correct correlation.

**Tmux session name**
: The tmux session housing the agent CLI process. One tmux session per agent*runtime session. Naming convention: `tc*<session_id_short>`.

**Agent** (per glossary — running-process lens)
: The agent CLI process — Claude, Codex, or Gemini — supervised within a tmux session.

**Active agent**
: The agent CLI currently bound to the session. Sessions may swap agents (e.g., a quota'd Gemini swapped for a Codex) but only one is active at a time.

**Session status**
: Lifecycle state of the live session: `active` (running), `idle` (no recent activity), `closed` (terminated).

**Session lifecycle event**
: A change in the session's lifecycle: started, updated, ended. Emitted by agent_runtime; consumed by `session_mirrors` and others.

**Operation**
: A long-running task tied to a session (file sync, build invocation). Tracked with a durable receipt; consumers wait on the completion event.

**Operation receipt**
: The persistent record of an operation: id, kind, status, started_at, completed_at, result. Consumers reference by id.

**Agent availability**
: Per-agent dispatch readiness state: available, unavailable (with reason), with an optional `until` recovery timestamp. Used by orchestrators to decide which agent to dispatch.

**Session runtime**
: The per-session actor owning live state: codex_input, codex_turn, metrics, cadence, wake_dirty, active_agent, control_queue. v2 replaces v1's scattered module-level dicts with this explicit actor.

**Session runtime registry**
: The map from session_id to SessionRuntime. Owned by the daemon binary. Replaces v1's module-level globals.

**Hook lane**
: One of three signal lanes. Authoritative for events where native agent hooks exist (Claude's pre-tool-use, post-tool-use, etc.). Never replaced by other lanes.

**Render lane**
: One of three signal lanes. Authoritative for Codex live semantic inference from tmux `capture-pane` snapshots. Codex emits no native hooks, so rendered terminal state is the only live source.

**Transcript lane**
: One of three signal lanes. Durable reconciliation/backfill only. NOT live authority. Used for post-turn access, restart recovery, safety-net backfill.

**Wake signal**
: The dirty-marking mechanism. `pipe-pane -o` is attached to Codex sessions; bytes arriving set `wake_dirty = true`. Triggers a capture-pane snapshot on the next cadence cycle.

**Cadence**
: The polling cadence state of a session: `fast` (0.5s), `slow` (5.0s), `audit` (30.0s). State machine transitions: fast → slow after idle window; slow → fast on wake/input/trigger.

**Control queue**
: Per-session ephemeral async queue routing compound control actions (escape-with-args style). Returns a `ControlReceipt` immediately; an internal worker drains sequentially handling tmux timing. Simple single-key controls remain direct.

**Replay corpus**
: Codex pane snapshot fixtures (`tests/fixtures/codex_pane_snapshots/`) used as the parity safety net for the Rust rewrite of the Codex semantic parser. Includes: startup_prompt, typing_partial, spinner_active, tool_action_read, tool_done_prompt, compact_fast_turn, stale_scrollback, seeded_prompt.

### Aggregates

#### Session (aggregate, the runtime ledger)

- **Root:** `Session`
- **Contains:** `session_id`, `teleclaude_session_id` (same), `native_session_id`, `tmux_session_name`, `agent` (active), `principal_binding` (the human/machine principal who started the session), `status`, `started_at`, `last_activity`, `closed_at` (nullable), `project_path` (filesystem path for live operations), `project_slug` (stable identifier for event payloads), `additional_context` (free-text passed at session start), `native_file_path` (transcript file location for live operations + extraction at session-end), the bound adapter id (nullable).
- **Invariants:**
  - `session_id` is generated at session start; never reused.
  - Tmux session name is unique; the daemon refuses to start a session whose tmux name collides.
  - Status transitions are forward: active → idle → closed. No reactivation; a new session for "the same conversation continued" gets a new session_id.
  - Native session id is set at the moment the agent CLI first emits its identifier (may lag session start by 1-2 seconds).
  - Native file path is recorded as soon as the agent CLI's transcript file location is known. Required at session-end so session_mirrors can extract.
  - `closed_at` is non-null when status is `closed`; null otherwise.
  - A session has exactly one active agent at any time (swaps are atomic).
  - Both `project_path` (for live ops) and `project_slug` (for event payloads) are carried.
- **Identifier:** `session_id` (UUID).
- **Lifecycle:** Created on `telec sessions start`. Status transitions during life. Ended on `telec sessions end` OR detected death (tmux session disappears). Record persists in Postgres after end for an **operational retention window** (~1-2 weeks, configurable). **Pruned after the window** — the durable historical record lives in `session_mirrors`, which extracted at session-end. The mirror persists forever, independent of this row's lifetime.

#### SessionRuntime (aggregate, in-memory per session)

- **Root:** `SessionRuntime`
- **Contains:** `session_id` (reference), per-session live state (codex_input, codex_turn, metrics, cadence, wake_dirty, active_agent), the control queue, the active timers.
- **Invariants:**
  - Exactly one SessionRuntime per active session.
  - State is in-memory; survives daemon restarts only insofar as it's reconstructable from durable state (Postgres session + transcript reconciliation).
  - Wake_dirty is cleared when a capture-pane snapshot is consumed for the dirty period.
  - Cadence transitions are atomic: a single function advances state.
- **Identifier:** `session_id`.
- **Lifecycle:** Created when the daemon notices an active session needing supervision (startup, new session, restart-recovery). Destroyed when the session reaches `closed`.

#### Operation (aggregate)

- **Root:** `Operation`
- **Contains:** `operation_id` (UUID), `session_id` (the session that initiated it), `kind` (e.g., `file_sync`, `build`, `migration`), `status` (`running` | `completed` | `failed`), `started_at`, `completed_at`, `result_payload`.
- **Invariants:**
  - Operations are tied to a single session (creator). They may outlive the session if the operation is long-running and async.
  - Status transitions are forward: running → (completed | failed). No retries on a single operation_id; retries get a new operation_id.
  - Result_payload is opaque to agent_runtime; only the operation_id is meaningful for routing.
- **Identifier:** `operation_id` (UUID).
- **Lifecycle:** Created when a session initiates a long-running task. Completed/failed when the task ends. Records persist for audit.

#### Agent Availability (aggregate)

- **Root:** `AgentAvailability` (one row per agent type per machine)
- **Contains:** `agent` (claude | codex | gemini), `available` (bool), `reason` (string, nullable), `until` (timestamp, nullable).
- **Invariants:**
  - Exactly one availability row per agent per machine.
  - When `available = false`, `reason` MUST be populated.
  - When `until` is set, the row auto-reverts to available at that timestamp (the daemon polls availability rows on cadence).
- **Identifier:** `(agent, machine)`.
- **Lifecycle:** Initialized at daemon startup. Mutated by `telec agents status <agent> --status ...`. Persists across restarts.

#### HookReceiver (in-memory, daemon-hosted)

- **Root:** `HookReceiver` (one per daemon instance)
- **Contains:** the IPC listener for `telec-hook` deliveries; the windowed-batch-write coordinator (window timer + dirty-set keyed by session_id); the urgent-flush escape hatch for latency-sensitive hook kinds.
- **Invariants:**
  - Exactly one HookReceiver per daemon instance.
  - Hook events arrive via IPC from `telec-hook` subprocesses. `telec-hook` is part of `agent_runtime`'s binary set (NOT integration's).
  - `telec-hook` retries delivery with backoff for ~10s if the daemon is unreachable; beyond that, the hook is lost. Accepted trade-off — agent CLIs do not replay hooks.
  - Hook events collected in a window (e.g., 1s) are coalesced per session_id (one batched update per session, regardless of how many hooks fired for it in the window).
  - At window tick: batched UPDATE in a single Postgres transaction over the dirty-set.
  - Urgent hook kinds (`agent_stop`, `session_end`) trigger immediate window flush — they bypass the window for latency reasons.
  - No `integration.inbox` for agent hooks. The window is the in-memory inbox; durability comes from the database write on commit (LISTEN/NOTIFY trigger for downstream events; see windowed-batch-write-and-dispatch feature spec).
- **Identifier:** the daemon process itself (singleton per daemon).
- **Lifecycle:** Created at daemon startup. Receives hooks throughout the daemon's lifetime. Cleaned up at daemon shutdown; in-flight window is lost on crash (~1s of hooks; acceptable per trade-off).

#### ExtractorCursor (aggregate, source-owned cursor bookkeeping)

- **Root:** `ExtractorCursor` (one row per `(consumer_id, session_id)` pair)
- **Contains:** `consumer_id` (the registered subscriber identifier, e.g., `memory-miner`, `session-history`), `session_id` (the session being tracked), `last_processed_position` (turn count or block index — natural unit per session), `last_processed_at`.
- **Invariants:**
  - One row per `(consumer_id, session_id)` pair.
  - Cursor advances on explicit consumer ack via `telec sessions ack` — never auto-advances on read.
  - First-ever read for a (consumer, session) pair returns content from the session's start; row is created on first successful ack.
  - Consumer ids are free-form strings; no central registry. A new consumer simply appears on first call.
  - Cursors are NEVER pruned when their session is pruned from `agent_runtime.sessions`. The cursor row may outlive its session record briefly; reconciliation cleans orphans.
- **Identifier:** `(consumer_id, session_id)`.
- **Lifecycle:** Created on first ack from a (consumer, session) pair. Updated on each subsequent ack. Operator can reset via `telec sessions cursors reset --consumer <id>`. Pruned when both the session record AND no recent ack activity from the consumer indicate the cursor is dead.

### Extract-window mechanism (source-side primitive)

agent_runtime exposes a single source primitive for downstream consumers (session_history, memory-miner, future consumers):

- `telec sessions extract-window --consumer <id> [--session <id>]` — returns new content since the consumer's cursor, per session, with rich content (all block types: user_text, assistant_text, thinking, tool_use, tool_result). Cursor is NOT auto-advanced.
- `telec sessions ack --consumer <id> --position <X> [--session <id>]` — advances the cursor after the consumer has safely processed.
- `telec sessions cursors list` — operator visibility into all consumers + their positions.
- `telec sessions cursors reset --consumer <id> [--session <id>]` — operator override; rewinds a cursor for re-processing.

The runtime can coalesce reads when multiple consumers want overlapping windows (one DB read per snapshot, fanned out to each consumer's filtered result). Implementation optimization; not an API concern.

**Trigger model.** Scheduler tick (see `scheduler.tick.*` events) is the trigger; per-pillar consumers subscribe and decide for themselves when to act based on their own cadence policy (e.g., the memory-miner acts on sessions idle ≥30 minutes or just-closed).

### Domain events emitted

#### `agent_runtime.session.started`

- **Producer:** `agent_runtime`
- **Emitted when:** a new session is created and the agent CLI is launched.
- **Payload:** `session_id`, `teleclaude_session_id`, `native_session_id` (may be null if not yet known), `tmux_session_name`, `agent`, `principal_binding`, `project_slug`, `started_at`.
- **Visibility:** CLUSTER
- **Known consumers:** `frontend` (live session list refresh), `integration` (notification when a session starts on the operator's behalf, optionally).
- **Idempotency key:** `session_id`.
- **Posture:** dispatched via LISTEN/NOTIFY trigger after the batched write commits (see `feature/agent_runtime/windowed-batch-write-and-dispatch`).

#### `agent_runtime.session.updated`

- **Producer:** `agent_runtime`
- **Emitted when:** state changes — typically AS A BATCHED EVENT covering all sessions changed in a window. May carry many sessions per event.
- **Payload:** list of `{session_id, change_summary, updated_at, field_changes}` entries — one per session updated in the window.
- **Visibility:** CLUSTER
- **Known consumers:** `frontend` (live UI refresh — iterates the batch), `telec-tui` (cache invalidation).
- **Idempotency key:** per-entry `(session_id, updated_at)`; consumer dedups.
- **Posture:** dispatched via LISTEN/NOTIFY trigger after the batched write commits. The window collects hook events; the batched write fires the trigger; the LISTEN'er publishes the batched Redis event with all updated session records as payload.

#### `agent_runtime.session.ended`

- **Producer:** `agent_runtime`
- **Emitted when:** the session transitions to `closed` — either by explicit end or detected death. **Urgent-flushed** (does NOT wait for window).
- **Payload:** `session_id`, `closed_at`, `closure_reason` (`explicit` | `tmux_died` | `agent_quit` | `operator_terminated`), `agent`, `project_slug`, `human_email`, `started_at`, **`native_file_path`** (required for `session_mirrors` extraction).
- **Visibility:** CLUSTER
- **Known consumers:** `session_mirrors` (closes ingestion, final projection), `identity` (auto-revoke session token), `frontend` (list update), `integration` (potentially: closure notification).
- **Idempotency key:** `(session_id, closed_at)`.
- **Posture:** `commit-then-emit`.

#### `agent_runtime.operation.completed`

- **Producer:** `agent_runtime`
- **Emitted when:** an operation transitions to `completed` or `failed`.
- **Payload:** `operation_id`, `session_id`, `kind`, `status`, `completed_at`, `result_summary`.
- **Visibility:** CLUSTER
- **Known consumers:** `workflow` (advances todo phase when operation completes a lifecycle step), `frontend` (operation status badge), orchestrators waiting on the operation.
- **Idempotency key:** `operation_id`.
- **Posture:** `commit-then-emit`.

### Hook ingestion (NOT a consumed event — agent_runtime receives directly)

Agent CLI hooks arrive at `agent_runtime` via the `telec-hook` subprocess (binary owned by agent_runtime). NOT through `integration` — see `transport-rules.md` change-axis correction: agent CLIs are systems we control, not external integration. Hook reception flow:

1. Agent CLI fires hook → spawns `telec-hook` subprocess
2. `telec-hook` reads payload from stdin, delivers to daemon via IPC (retries ~10s on disconnect)
3. Daemon's `HookReceiver` collects the event in the current window keyed by session_id
4. Window tick (or urgent flush for `agent_stop` / `session_end`): batched UPDATE of all dirty sessions in a single Postgres transaction
5. Trigger on commit fires `NOTIFY` with the affected session_ids
6. LISTEN'er reads the records and publishes the batched Redis event(s)

Hook kind → reaction:

- `session_start` → mark session active, set native_session_id, set native_file_path if newly learned
- `pre_tool_use`, `post_tool_use` → update activity, advance cadence to fast
- `user_prompt_submit` → mark turn boundary
- `agent_stop` → **urgent flush** — emit `session.updated` immediately (HOOK LANE AUTHORITATIVE for stop)
- `session_end` → **urgent flush** — emit `session.ended` with the full payload (carries native_file_path for session_mirrors extraction)

Failure handling: if `telec-hook` cannot deliver within its retry window (~10s), the hook is lost. Acceptable per the design trade-off — agent CLIs do not replay hooks. Render lane and transcript lane act as safety nets for live observability; periodic reconciliation catches drift.

### Domain events consumed

#### `integration.inbox.received` (external inbound only)

- **Producer:** `integration`
- **Reaction:** inbound messages from EXTERNAL providers (Telegram, Discord, WhatsApp) targeted at a session are routed through agent_runtime to the appropriate session's input queue. Note this is NOT agent CLI hooks (those come direct via telec-hook); only true external messaging.
- **Failure handling:** undeliverable messages (session ended, session not found) are returned to integration's dead-letter.

#### `config.effective.updated`

- **Producer:** `config`
- **Reaction:** re-read per-agent dispatch defaults, polling cadence configuration, tmux configuration.
- **Failure handling:** stale config tolerated for one operation.

#### `identity.token.revoked`

- **Producer:** `identity`
- **Reaction:** if a session token is revoked, the corresponding session's adapter binding is cleaned up (the adapter can no longer authenticate).
- **Failure handling:** retry the cleanup; orphan adapter bindings get caught by reconciliation.

### Use cases

#### Feature spec index

The bounded context's feature specs (hub-and-spoke spokes — see `software-development/principle/documentation-first-development`):

- **v1 (`applies_to: v1`, `status: actual`)** — authored by `inventory-v1-agent-runtime`. Source-grounded inventory of live v1 behavior; authoritative until the daemon swap.
  - [agent-restart](../feature/agent_runtime/agent-restart.md) — restart the agent process inside an existing live session.
  - [daemon-lifecycle](../feature/agent_runtime/daemon-lifecycle.md) — daemon startup, shutdown, session/projects cache warming, API-server restart loop.
  - [direct-conversation-links](../feature/agent_runtime/direct-conversation-links.md) — bidirectional session-to-session message routing via `--direct` ignition.
  - [output-polling-and-delivery](../feature/agent_runtime/output-polling-and-delivery.md) — per-session background polling, transcript projection, dedup digest, delivery.
  - [run-session-with-command](../feature/agent_runtime/run-session-with-command.md) — start a session preloaded with a slash command as its first agent message.
  - [session-cleanup-and-reaping](../feature/agent_runtime/session-cleanup-and-reaping.md) — terminate sessions, free tmux/workspace/tmpdir resources, sweep orphans.
  - [session-input-delivery](../feature/agent_runtime/session-input-delivery.md) — deliver text and keystroke input into running sessions via tmux.
  - [session-lifecycle](../feature/agent_runtime/session-lifecycle.md) — start, list, and explicitly end agent sessions over the HTTP API.
  - [session-revival](../feature/agent_runtime/session-revival.md) — revive an ended or unbound session by binding the prior transcript chain to a fresh agent process.
  - [session-subscriptions](../feature/agent_runtime/session-subscriptions.md) — listener-based stop / input-request notification fan-out.
  - [session-transcript-retrieval](../feature/agent_runtime/session-transcript-retrieval.md) — on-demand read of a session's native transcript via the messages endpoint.
  - [tmux-pane-orchestration](../feature/agent_runtime/tmux-pane-orchestration.md) — the tmux-bridge primitive surface used to host agent CLI processes.
- **v2 (`applies_to: v2`, `status: target`)** — authored alongside the v2 rewrite.
  - [windowed-batch-write-and-dispatch](../feature/agent_runtime/windowed-batch-write-and-dispatch.md) — windowed batched write + LISTEN/NOTIFY dispatch for agent CLI hook events.

The Gherkin scenarios below (UC-ART-1 through UC-ART-9) describe the v2 target behavior of the bounded context. Per-capability v1-vs-v2 contracts live in the feature specs above.

#### UC-ART-1: Start a new session with an agent CLI

```
Given an operator runs `telec sessions start --agent claude --project /path/to/work`
When the daemon receives the start request
Then agent_runtime creates a Session aggregate (session_id, tmux_session_name)
And launches the agent CLI inside tmux
And creates a SessionRuntime actor for live state
And requests a session token from identity (UC-IDN-2)
And emits agent_runtime.session.started
And returns the session_id to the operator
```

#### UC-ART-2: Three-lane signal coordination — Codex turn

```
Given a Codex session is running
And the operator types into the session
When the daemon's wake signal fires (pipe-pane bytes arrive)
Then SessionRuntime marks wake_dirty
And on the next cadence cycle, capture-pane is invoked
And the render lane parses the snapshot — recognizes a tool_use start
And synthesizes a tool_use event into the session output stream
And cadence advances to fast (turn active)
And the same content lands in the transcript file at end-of-turn
And the transcript lane backfills for any render-lane gaps (safety net only)
And agent_stop hook (when it eventually fires for Codex equivalents) is authoritative for turn end
```

#### UC-ART-3: Adaptive cadence — idle session

```
Given a session has been at fast cadence (0.5s) but no wake signal arrives for 10s
When the cadence state machine transitions
Then cadence advances to slow (5.0s)
And capture-pane is skipped on subsequent ticks when wake_dirty is false and audit is not due
And tmux subprocess load drops dramatically
When a wake signal arrives (operator types, agent CLI redraws)
Then cadence reverts to fast immediately
```

#### UC-ART-4: Compound control via ephemeral queue

```
Given an operator sends an "escape + text + enter" compound control
When agent_runtime routes the control
Then the SessionRuntime's control_queue receives the ControlAction
And returns a ControlReceipt immediately to the caller (non-blocking)
And the internal worker drains the queue, handling the tmux 1s timing for text+enter
And the actual tmux interaction completes asynchronously
Compare: simple single-key controls (just escape with no args) remain DIRECT — no queue
```

#### UC-ART-5: Session restart recovery

```
Given the daemon restarts unexpectedly
And five active sessions existed before the restart
When the daemon comes back up
Then agent_runtime queries Postgres for sessions whose status is active and tmux session exists
And reconstructs a SessionRuntime actor for each
And starts the pipe-pane wake signal for each Codex session
And takes a reconciliation snapshot via capture-pane (because pipe-pane is prospective and missed any state before the restart)
And resumes normal cadence loop
And no session is lost; humans see continuity
```

#### UC-ART-6: Operation tracking — long-running build

```
Given a session initiates a build via an operation
When agent_runtime creates the Operation aggregate (operation_id, status=running)
And launches the build async
Then a workflow orchestrator subscribed to agent_runtime.operation.completed waits
When the build completes
Then agent_runtime sets status=completed (or failed) and result_payload
And emits agent_runtime.operation.completed
And the workflow orchestrator picks up the event and advances its todo phase
```

#### UC-ART-7: Agent availability swap mid-flight

```
Given a session is running on Gemini
And Gemini hits its quota mid-turn
When the agent_runtime detects the quota failure
Then it marks Gemini unavailable (telec agents status gemini --status unavailable --reason quota --until <reset>)
And dispatches a new builder on Codex (the orchestrator's responsibility, but agent_runtime exposes the availability state)
And the original session_id continues with the new agent (active_agent swap)
And agent_runtime.session.updated fires with the swap
```

#### UC-ART-8: Cadence config consumption

```
Given config exposes polling.fast_interval_s, polling.slow_interval_s, polling.idle_transition_s, polling.audit_interval_s
When agent_runtime starts a session
Then it reads these values from effective configuration
And applies them to the cadence state machine
When config.effective.updated fires with polling keys changed
Then agent_runtime updates running sessions' cadence parameters
```

#### UC-ART-9: Replay corpus parity verification

```
Given the v2 Codex semantic parser is implemented in Rust
When the test suite runs against the replay corpus fixtures
Then each fixture's expected events match the parser's output
And any divergence is a defect — the parser must be corrected, the fixture must NOT be loosened
And the corpus is the binding parity test against v1's Python parser behavior
```

### Context map position

- **Partnership with `session_mirrors`** — tightly coordinated; share `session_id` namespace; ledger is downstream consumer of session lifecycle events.
- **Customer-Supplier downstream of `identity`** — sessions bind principals; session tokens come from identity.
- **Customer-Supplier downstream of `integration`** — for TRUE external messaging only. Subscribes to `integration.inbox.received` for inbound messages from external providers (Telegram, Discord, WhatsApp) targeted at sessions. Agent CLI hook reception is NOT in this relationship — agent_runtime owns `telec-hook` and processes those hooks directly.
- **Partnership with `session_mirrors`** — agent_runtime emits `session.ended` with native_file_path + identity fields; session_mirrors consumes to extract the eternal text mirror. The runtime ledger is operational (pruned after ~1-2 weeks); the mirror is the durable historical archive.
- **Customer-Supplier upstream to `workflow`** — operation.completed events drive todo phase advancement.
- **Reads from `config`** — cadence parameters, per-agent defaults, tmux configuration.
- **NO anti-corruption layer with v1 as a separate cutover.** The v2-agent-runtime → v2-agent-runtime swap IS the cutover. When `v2-agent-runtime` ships, the v1 daemon is replaced and v1 session management dies with it. There's no parallel-capable session management — only one daemon runs at a time on a machine.

## Allowed values

- `session status`: `active`, `idle`, `closed`.
- `closure_reason`: `explicit`, `tmux_died`, `agent_quit`, `operator_terminated`.
- `agent`: `claude`, `codex`, `gemini` (extensible per agent_artifacts deployment targets).
- `operation status`: `running`, `completed`, `failed`.
- `cadence mode`: `fast`, `slow`, `audit`.

## Known caveats

- **Tmux sessions survive daemon restart.** Long-running music, builds, and active conversations don't die when the daemon does. Reconciliation rebuilds SessionRuntime actors on daemon restart.
- **Pipe-pane is wake signal ONLY.** It's not a substitute for `capture-pane` output. Pipe-pane is corrupted by command echo, prompt redraws, bracketed-paste toggles, and CR-in-place updates. The semantic parser needs rendered-screen snapshots.
- **`capture-pane` budget vs lookback are different concepts.** v1 regression conflated them. v2 keeps `CAPTURE_PANE_LOOKBACK_LINES` (default 500) separate from char-budget constants.
- **Codex emits no native hooks** — the render lane is its primary live source. Other agents (Claude with hooks) get hook-lane authority and use the render lane for cross-agent unified behavior only.
- **`agent_stop` is HOOK-AUTHORITATIVE always.** Even when other lanes have signals about stop, agent_stop hook wins.
- **No retries on a single operation_id.** Retries are fresh operations with new IDs; the consumer must handle multiple operations resolving the same logical task (use semantic dedupe on the consumer side if needed).
- **Per-session tmp directory cleanup is integrated with teardown.** No second cleanup system. Orphan-tmp-dir sweep follows the orphan-workspace pattern.
- **Reducing tmux load is the cadence state machine's job.** Not parallelism. Offloading subprocess work to another worker without throttling doesn't help — the cost is the subprocess count, which the cadence machine reduces.
- **Three lanes never replace each other.** The hook lane is authoritative where native hooks exist; the render lane is authoritative for Codex semantics; the transcript lane is durable backup. Trying to make one lane "replace" another is a design defect.
- **The control queue is for compound actions only.** Simple single-key controls (just escape) remain direct because they're latency-sensitive and queue overhead helps nothing.
- **Cutover IS the daemon swap.** No standalone v2-agent-runtime-cutover. v2-agent-runtime ships the new daemon binary that hosts v2-agent-runtime; v1 daemon dies the same day.
