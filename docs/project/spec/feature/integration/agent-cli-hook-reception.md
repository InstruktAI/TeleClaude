---
description: 'Subprocess receiver invoked by agent CLIs (Claude, Codex, Gemini) that parses a hook payload, resolves a TeleClaude session, and enqueues the event for integration-side processing.'
visibility: 'public'
---

# Agent CLI Hook Reception — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

The receiver subprocess that an agent CLI invokes for every hook event it
emits (`session_start`, `user_prompt_submit`, `tool_use`, `agent_stop`,
`agent_error`, plus event-name variants per agent). It reads the hook
payload from its standard input, selects a per-agent adapter (Claude /
Codex / Gemini) to normalize agent-specific field names, maps the raw
event name to a canonical hook event type, resolves or refreshes a
TeleClaude session identifier from the agent's native session id, and
enqueues the event into the per-session hook outbox. The receiver also
emits adapter-formatted "additional context" on `agent_session_start`
and, on `agent_stop`, may emit an adapter-formatted checkpoint-block
response that the agent CLI interprets as a blocking instruction.

Conceptually this surface belongs to the `agent_runtime` bounded context;
it is inventoried under `integration` because the receiver shares its
outbox writer, payload model, and process-boundary plumbing with the
third-party webhook subsystem.

## Canonical fields

### Payload model

The receiver constructs typed, frozen (immutable) internal payload models in
`teleclaude/core/adapter_client.py`, defined in `teleclaude/core/events.py`:

- `AgentSessionStartPayload`
- `AgentStopPayload`
- `AgentNotificationPayload`
- `AgentSessionEndPayload` (reserved)

Required fields are enforced via direct field access — no `.get` fallbacks.
Adapters never mutate payloads; the daemon generates summaries on `stop` events
by summarizing the transcript markdown from `teleclaude/utils/transcript.py`
(`parse_session_transcript(...)`). The receiver writes events to the
`hook_outbox` table as `{session_id, event_type, data}` (see `hook-event-outbox`),
which the daemon's `_hook_outbox_worker` drains (see `hook-outbox-dispatcher`).

### Use cases

#### UC-R1: Claude session_start with additional context injection

```gherkin
Given Claude Code is configured with a SessionStart hook pointing at the receiver
And the project has memory snippets and a configured human-in-the-loop person
When Claude starts a new session and invokes the receiver for SessionStart
Then the Claude adapter parses the hook payload
And the receiver maps the event to the canonical agent-session-start hook event
And the receiver resolves the TeleClaude session id (minting one when missing — agent-session-start is a mint event)
And the receiver fetches memory context and the person header for the project
And emits adapter-formatted additional context (plain text for Claude)
And persists the native session id and native log file as a native-metadata-update outbox entry
And enqueues the agent-session-start event into the per-session hook outbox
And signals success to the agent CLI
```

#### UC-R2: Stop hook blocked with checkpoint instruction

```gherkin
Given a Claude session has uncommitted turn-local changes
Or the session's current HEAD differs from the turn-start anchor SHA on main
And the persistent checkpoint clear flag is not set
And the post-commit review flag for the current HEAD has not already fired
When Claude invokes the receiver with a Stop event after the agent attempts to stop
Then the receiver maps the event to agent-stop
And the checkpoint engine evaluates the session row and gathers evidence
And the engine returns a non-empty checkpoint reason
And when HEAD advanced on main, the reason includes the post-commit review-gate surfacing action even if no dirty files remain
And that action instructs the agent to set a conditional 5-minute heartbeat when it recommends review
And if the heartbeat fires without a user response approving or declining review, the agent dispatches the commit(s) to review and waits for REVIEW COMPLETE
And repeated Stop hooks for the same HEAD do not include that action again
And a checkpoint-seen outbox entry is recorded
And the Claude adapter formats a block decision carrying the reason
And the receiver emits the block decision to the agent CLI BEFORE the agent-stop event is enqueued
And Claude reads the block decision and re-prompts itself with the checkpoint reason
```

#### UC-R3: Codex subagent event dropped pre-resolution

```gherkin
Given Codex emits a hook event from a subagent transcript path
When the receiver detects the event originates from a subagent transcript
Then the event is dropped BEFORE session resolution runs
And no session-map entry is written that would bind the subagent native id to the parent session
And the receiver exits cleanly with no outbox row
And a subagent-drop debug log is recorded
```

#### UC-R4: System-injected user_prompt_submit dropped

```gherkin
Given Claude posts a user-prompt-submit event whose prompt body starts with "[TeleClaude Checkpoint]" or another TeleClaude-owned envelope prefix
When the receiver processes the event
Then the receiver recognizes the system-injected envelope
And the event is dropped (no outbox row written)
And the per-turn recheck flag is NOT reset
```

#### UC-R5: Unhandled hook event silently dropped

```gherkin
Given an agent emits a hook event whose canonical type is outside the receiver-handled set
When the receiver processes the event
Then a "dropped unhandled hook event" debug log is emitted
And the receiver exits cleanly with no outbox row written
```

#### UC-R6: Invalid payload — best-effort error path

```gherkin
Given the agent CLI invokes the receiver with a malformed payload
When the receiver attempts to parse via the adapter
Then the parse failure is caught
And the best-effort error helper is invoked with an invalid-payload code
And inside that helper:
    - no raw payload data is available for session resolution
    - cached session lookup returns no result
    - native-session lookup returns no result
    - the helper logs "receiver error with unknown session" at error level
    - NO outbox row is enqueued
And the receiver exits with a failure status

Given a hypothetical caller path that did supply payload data with a resolvable native session id
When the error helper runs
Then session resolution succeeds and an error outbox row IS enqueued
But the parse-failure path does NOT supply such data, so this branch is not reached on the parse path
```

#### UC-R7: Receiver runs under the project venv

```gherkin
Given the receiver is invoked by an agent CLI from an arbitrary working directory where the resolved Python is the system Python
When the receiver bootstrap resolves the repo root
And finds a project virtualenv interpreter beneath it
Then the receiver re-executes under the project virtualenv interpreter
And continues with the same arguments under that interpreter
And all project dependencies are importable
```

### Cross-context references

- Primary home is `agent_runtime` per `docs/project/spec/domain/context-map.md`
  ("Agent CLI hooks reach agent_runtime directly via the receiver IPC").
  This feature is inventoried under `integration` because the receiver
  shares its outbox writer, payload model, and process-boundary plumbing
  with the third-party webhook subsystem.
- Consumes session-map state owned by the `agent_runtime` context
  (sessions and native-session-id mapping).
- Emits checkpoint-seen, native-metadata-update, native-session-refresh,
  agent-session-start, user-prompt-submit, tool-use, agent-stop, and
  agent-error entries into the hook outbox (see `hook-event-outbox`).

## Known caveats

- The receiver only emits events that belong to the receiver-handled
  canonical set; intermediate hook traffic outside that set is
  intentionally dropped at the process boundary to prevent noisy events
  reaching downstream handlers.
- Adapter mint sets are:
  - Claude mints on agent-session-start.
  - Gemini mints on agent-session-start.
  - Codex mints on BOTH agent-session-start and agent-stop, because its
    hook surface emits agent-stop even when no prior session-start was
    observed (e.g., manual `codex` invocations whose first observable
    hook is the stop). For non-mint events on an unknown native session
    id, the receiver drops the event rather than minting.
- The system-injected prompt filter strips out TeleClaude-injected
  envelopes (`[TeleClaude Checkpoint]`, `[TeleClaude Notification]`,
  `[TeleClaude Input Request]`, `[TeleClaude Linked output...]`), Codex
  internal hook-prompt markers, and Claude hook-feedback prefixes
  ("Stop hook feedback:", "PreToolUse hook feedback:") plus internal
  task-notification and system-reminder envelopes. Without this filter,
  agents would treat their own injected prompts as new user input and
  loop.
- All three v1 adapters support hook checkpoints. The block decision
  shape differs per adapter:
  - Claude → block decision with reason.
  - Codex → block decision with reason.
  - Gemini → deny decision with reason.
    When the adapter returns no decision, the receiver lets the stop event
    continue to outbox enqueue; no v1 adapter exercises that branch.
- Native metadata persistence always runs when a native session id or
  native log file is present. When the new native session id differs
  from the stored value, a native-session-refresh outbox entry is
  emitted in addition to the standard native-metadata-update.
- The hook input must be a structured payload object; an unstructured
  payload is rejected at the adapter boundary and reported through the
  same best-effort unknown-session path as a malformed payload: an
  error is logged, no error outbox row is enqueued, and the receiver
  exits with a failure status.
- The receiver swallows persistence errors during native-metadata
  writes with a warning log; the hook event itself is still enqueued.
