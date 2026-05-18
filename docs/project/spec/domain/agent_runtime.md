---
id: project/spec/domain/agent_runtime
type: spec
domain: software-development
scope: project
visibility: public
status: target
delivered_by: [v2-agent-runtime, v2-daemon-narrow]
description: Agent Runtime bounded context — live agent sessions, tmux orchestration, agent CLI supervision, three-lane signal architecture. The heart of v2 — the genuine daemon-shaped part of the platform.
---

# Agent Runtime Domain Spec — Spec

## Required reads

- @docs/global/software-development/principle/domain-driven-design.md
- @docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md

## What it is

The `agent_runtime` bounded context owns LIVE agent sessions — the tmux processes, the supervised agent CLIs (Claude, Codex, Gemini), the input/output streaming, the moment-by-moment session state. It binds an `agent` (a process) to a `principal` (an identity) and tracks lifecycle from start to end.

Three signal lanes (hook, render, transcript) coordinate the live state — each lane authoritative for what it owns; never replacing each other. A per-session `SessionRuntime` actor holds state, an adaptive cadence state machine throttles tmux probes, and an ephemeral control queue routes compound interactions that would otherwise block the caller.

This context is the genuine daemon-shaped part of the platform. The `telec-daemon` binary embeds it in long-running form. CLI and TUI also embed for read queries. The cutover from v1 to v2 IS the daemon swap — there's no separate `v2-agent-runtime-cutover`.

This context does NOT own: local project bookkeeping (`workflow`), historical session record (`session_ledger`), knowledge storage (`knowledge`), UI/business logic, hook ingestion (`integration` owns `telec-hook` and the subprocess hook event family).

## Canonical fields

### Ubiquitous language

**Session** (per glossary — live dimension)
:  A unit of agent work in progress. Has a tmux name, native session id, principal binding, status, last activity, project path, additional context. The thing humans see in the session list.

**Session id**
:  UUID identifying the session. Shared with `session_ledger` (same id, different lens). The wire identifier in events.

**TeleClaude session id**
:  Same as session_id. Used in cross-context contexts where "session id" alone might be ambiguous.

**Native session id**
:  The agent CLI's internal session identifier. Different per agent: Claude has one format, Codex another, Gemini another. Stored explicitly to enable correct correlation.

**Tmux session name**
:  The tmux session housing the agent CLI process. One tmux session per agent_runtime session. Naming convention: `tc_<session_id_short>`.

**Agent** (per glossary — running-process lens)
:  The agent CLI process — Claude, Codex, or Gemini — supervised within a tmux session.

**Active agent**
:  The agent CLI currently bound to the session. Sessions may swap agents (e.g., a quota'd Gemini swapped for a Codex) but only one is active at a time.

**Session status**
:  Lifecycle state of the live session: `active` (running), `idle` (no recent activity), `closed` (terminated).

**Session lifecycle event**
:  A change in the session's lifecycle: started, updated, ended. Emitted by agent_runtime; consumed by `session_ledger` and others.

**Operation**
:  A long-running task tied to a session (file sync, build invocation). Tracked with a durable receipt; consumers wait on the completion event.

**Operation receipt**
:  The persistent record of an operation: id, kind, status, started_at, completed_at, result. Consumers reference by id.

**Agent availability**
:  Per-agent dispatch readiness state: available, unavailable (with reason), with an optional `until` recovery timestamp. Used by orchestrators to decide which agent to dispatch.

**Session runtime**
:  The per-session actor owning live state: codex_input, codex_turn, metrics, cadence, wake_dirty, active_agent, control_queue. v2 replaces v1's scattered module-level dicts with this explicit actor.

**Session runtime registry**
:  The map from session_id to SessionRuntime. Owned by the daemon binary. Replaces v1's module-level globals.

**Hook lane**
:  One of three signal lanes. Authoritative for events where native agent hooks exist (Claude's pre-tool-use, post-tool-use, etc.). Never replaced by other lanes.

**Render lane**
:  One of three signal lanes. Authoritative for Codex live semantic inference from tmux `capture-pane` snapshots. Codex emits no native hooks, so rendered terminal state is the only live source.

**Transcript lane**
:  One of three signal lanes. Durable reconciliation/backfill only. NOT live authority. Used for post-turn access, restart recovery, safety-net backfill.

**Wake signal**
:  The dirty-marking mechanism. `pipe-pane -o` is attached to Codex sessions; bytes arriving set `wake_dirty = true`. Triggers a capture-pane snapshot on the next cadence cycle.

**Cadence**
:  The polling cadence state of a session: `fast` (0.5s), `slow` (5.0s), `audit` (30.0s). State machine transitions: fast → slow after idle window; slow → fast on wake/input/trigger.

**Control queue**
:  Per-session ephemeral async queue routing compound control actions (escape-with-args style). Returns a `ControlReceipt` immediately; an internal worker drains sequentially handling tmux timing. Simple single-key controls remain direct.

**Replay corpus**
:  Codex pane snapshot fixtures (`tests/fixtures/codex_pane_snapshots/`) used as the parity safety net for the Rust rewrite of the Codex semantic parser. Includes: startup_prompt, typing_partial, spinner_active, tool_action_read, tool_done_prompt, compact_fast_turn, stale_scrollback, seeded_prompt.

### Aggregates

#### Session (aggregate, live)

- **Root:** `Session`
- **Contains:** `session_id`, `teleclaude_session_id` (same), `native_session_id`, `tmux_session_name`, `agent` (active), `principal_binding` (the human/machine principal who started the session), `status`, `started_at`, `last_activity`, `closed_at` (nullable), `project_path`, `additional_context` (free-text passed at session start), the bound adapter id (nullable).
- **Invariants:**
  - `session_id` is generated at session start; never reused.
  - Tmux session name is unique; the daemon refuses to start a session whose tmux name collides.
  - Status transitions are forward: active → idle → closed. No reactivation; a new session for "the same conversation continued" gets a new session_id.
  - Native session id is set at the moment the agent CLI first emits its identifier (may lag session start by 1-2 seconds).
  - `closed_at` is non-null when status is `closed`; null otherwise.
  - A session has exactly one active agent at any time (swaps are atomic).
- **Identifier:** `session_id` (UUID).
- **Lifecycle:** Created on `telec sessions start`. Status transitions during life. Ended on `telec sessions end` OR detected death (tmux session disappears). Record persists in Postgres after end for historical reference.

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

### Domain events emitted

#### `agent_runtime.session.started`

- **Producer:** `agent_runtime`
- **Emitted when:** a new session is created and the agent CLI is launched.
- **Payload:** `session_id`, `teleclaude_session_id`, `native_session_id` (may be null if not yet known; updated event fires when learned), `tmux_session_name`, `agent`, `principal_binding`, `project_path`, `started_at`.
- **Visibility:** CLUSTER
- **Known consumers:** `session_ledger` (opens transcript ingestion), `frontend` (live session list refresh), `integration` (notification when a session starts on the operator's behalf, optionally).
- **Idempotency key:** `session_id`.
- **Posture:** `commit-then-emit`.

#### `agent_runtime.session.updated`

- **Producer:** `agent_runtime`
- **Emitted when:** session state changes that aren't lifecycle transitions: `last_activity` advances, `active_agent` swaps, `additional_context` is mutated, native_session_id learned post-start.
- **Payload:** `session_id`, `change_summary`, `updated_at`, optional `field_changes` map.
- **Visibility:** CLUSTER
- **Known consumers:** `session_ledger` (marks dirty for projection), `frontend` (live UI refresh).
- **Idempotency key:** `(session_id, updated_at)`.
- **Posture:** `commit-then-emit`.

#### `agent_runtime.session.ended`

- **Producer:** `agent_runtime`
- **Emitted when:** the session transitions to `closed` — either by explicit end or detected death.
- **Payload:** `session_id`, `closed_at`, `closure_reason` (`explicit` | `tmux_died` | `agent_quit` | `operator_terminated`).
- **Visibility:** CLUSTER
- **Known consumers:** `session_ledger` (closes ingestion, final projection), `identity` (auto-revoke session token), `frontend` (list update), `integration` (potentially: closure notification).
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

### Domain events consumed

#### `integration.inbox.agent_hook_received` (and per-kind sub-channels)

- **Producer:** `integration`
- **Reaction:** agent_runtime is the primary consumer of agent CLI hook signals. Each hook kind triggers specific lifecycle behavior:
  - `session_start` → mark session active, set native_session_id if newly learned
  - `pre_tool_use`, `post_tool_use` → update activity, advance cadence to fast
  - `user_prompt_submit` → mark turn boundary
  - `agent_stop` → emit `session.updated` reflecting the stop (HOOK LANE AUTHORITATIVE for this)
  - `session_end` → trigger `session.ended` flow
- **Failure handling:** missed hooks fall back to render-lane and transcript-lane signals; the three-lane architecture means no single lane's failure breaks live observability. Periodic reconciliation catches drift.

#### `integration.inbox.received`

- **Producer:** `integration`
- **Reaction:** inbound messages targeted at a session (e.g., Telegram-routed `telec sessions send` from a remote user) are routed through agent_runtime to the appropriate session's input queue.
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

- **Partnership with `session_ledger`** — tightly coordinated; share `session_id` namespace; ledger is downstream consumer of session lifecycle events.
- **Customer-Supplier downstream of `identity`** — sessions bind principals; session tokens come from identity.
- **Customer-Supplier downstream of `integration`** — subscribes to `integration.inbox.agent_hook_*` for agent CLI lifecycle signals AND `integration.inbox.received` for inbound messages targeted at sessions. Integration owns the hook receiver binary (`telec-hook`); agent_runtime reacts to the events it emits.
- **Customer-Supplier upstream to `workflow`** — operation.completed events drive todo phase advancement.
- **Reads from `config`** — cadence parameters, per-agent defaults, tmux configuration.
- **NO anti-corruption layer with v1 as a separate cutover.** The v2-agent-runtime → v2-daemon-narrow swap IS the cutover. When `v2-daemon-narrow` ships, the v1 daemon is replaced and v1 session management dies with it. There's no parallel-capable session management — only one daemon runs at a time on a machine.

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
- **Cutover IS the daemon swap.** No standalone v2-agent-runtime-cutover. v2-daemon-narrow ships the new daemon binary that hosts v2-agent-runtime; v1 daemon dies the same day.
