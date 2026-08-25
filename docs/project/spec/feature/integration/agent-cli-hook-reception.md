---
description: 'Subprocess receiver invoked by agent CLIs that parses a hook payload, resolves a TeleClaude session, and enqueues the event for integration-side processing.'
visibility: 'public'
---

# Agent CLI Hook Reception — Spec

## What it is

The receiver subprocess that an agent CLI invokes for every hook event it
emits (`session_start`, `user_prompt_submit`, `pre_tool_use`, `post_tool_use`,
`agent_stop`, `agent_error`, plus event-name variants per agent). It reads the
hook payload from its standard input, selects a per-agent adapter to normalize agent-specific field names, maps the raw
event name to a canonical hook event type, resolves or refreshes a
TeleClaude session identifier from the agent's native session id, and
enqueues the event into the per-session hook outbox. The receiver also
emits adapter-formatted "additional context" on `agent_session_start`
and emits one adapter-formatted response at a control-delivery boundary. The
receiver composes a closed semantic intent — context, continuation reason, or
both — while each adapter owns the event-specific provider wire shape.

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

The normalized envelope keeps lineage and execution identity separate:

- The outbox row's `session_id` addresses the owning TeleClaude session.
- `native_session_id` identifies the agent execution that emitted the hook.
- `source_kind` distinguishes a managed primary, managed descendant, managed
  teardown invocation, or headless source.
- `headless_bootstrap` is receiver-owned authorization for creating an unknown
  headless row. Raw provider input cannot set this field.

### Use cases

#### UC-R1: Claude session_start with additional context injection

```gherkin
Given Claude Code is configured with a SessionStart hook pointing at the receiver
And the project has memory snippets and a configured human-in-the-loop person
When Claude starts a new session and invokes the receiver for SessionStart
Then the Claude adapter parses the hook payload
And the receiver maps the event to the canonical agent-session-start hook event
And the receiver resolves the TeleClaude session id, minting one only when the invocation has neither a managed identity marker nor tmux attachment
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
And that action instructs the agent to set a conditional five-minute reminder when it recommends review
And if the reminder fires without a user response approving or declining review, the agent dispatches the commit(s) to review and waits for REVIEW COMPLETE
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

#### UC-R8: Managed background child retains parent lineage without becoming a session

```gherkin
Given an agent process inherits a valid TeleClaude session identity marker
And the process has no tmux attachment
And its hook payload carries a native session id different from the managed primary binding
When the adapter classifies the invocation as a managed descendant
Then the receiver resolves the owning TeleClaude session from the marker
And retains the child native session id and managed-descendant source kind in the hook envelope
And never mints or authorizes a headless session for that invocation
And a descendant agent-session-start is dropped before context injection, metadata mutation, and outbox enqueue
And later handled activity hooks may be forwarded under the owning session
But the descendant native id and transcript path never replace the managed primary binding
```

#### UC-R9: Ambiguous marker-bearing invocation fails closed

```gherkin
Given a hook invocation has a session identity marker that is malformed, stale, or incompatible
When session resolution cannot prove a live managed owner
Then the receiver records the managed identity failure
And drops the event or uses the managed teardown fallback when applicable
And never enters the headless mint path
```

#### UC-R10: Antigravity hooks preserve the conversation lifecycle

```gherkin
Given an Antigravity agent starts a new conversation for a configured human
When the conversation reaches its first model invocation
Then TeleClaude registers exactly one session start before the model runs
And the agent receives the complete non-null person identity entry as transient system context
And that profile is valid, human-readable YAML beneath a single `human` root
And configured extension fields remain present
And per-person credentials, subscriptions, and runtime overlay settings are absent
And the provider receives its documented successful startup response
When the same execution invokes the model again
Then TeleClaude emits no session-start or user-prompt event
And performs no session lookup, checkpoint reset, context injection, or outbox write for that invocation
And the provider receives its documented neutral response
When the provider reports a tool invocation
Then TeleClaude records exactly one tool-activity event for the owning session
And the provider receives its documented successful tool-hook response
When the execution loop stops while provider-owned background work remains active
Then TeleClaude does not evaluate checkpoint obligations
And does not mark the turn complete, extract final output, or enqueue an agent-stop event
And the provider receives its documented stop-allowing response
When Antigravity later stops with all provider-owned background work complete
Then TeleClaude evaluates checkpoint obligations
And either returns the documented continuation response or enqueues exactly one agent-stop event
```

#### UC-R11: Control context uses each native event's model-facing channel

```gherkin
Given a control payload is pending when an installed agent hook reaches a delivery boundary
When the receiver composes the provider response
Then every provider receives a response valid for that native event
And no provider response contains a null continuation reason
And Claude and DeepSeek UserPromptSubmit context does not block or swallow the user's prompt
And Codex Stop carries context only through one non-empty block reason without hook-specific output
And Antigravity Stop carries context only through one non-empty continue reason without injection steps
And Antigravity PreInvocation and PostInvocation context uses injection steps without a decision
And the delivered context is observable in the agent transcript or the next model turn
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
- Adapter manifests own their explicit adoption points. The current providers
  mint on both agent-session-start and agent-stop because a native execution
  may first become observable at its stop boundary. For non-mint events on an
  unknown native session id, the receiver drops the event rather than minting.
- The system-injected prompt filter strips complete platform-control and
  identity envelopes through the shared registry, plus Codex
  internal hook-prompt markers, and Claude hook-feedback prefixes
  ("Stop hook feedback:", "PreToolUse hook feedback:") plus internal
  task-notification and system-reminder envelopes. Without this filter,
  agents would treat their own injected prompts as new user input and
  loop.
- All four adapters support hook checkpoints. The continuation response
  differs per provider:
  - Claude → block decision with reason.
  - Codex → block decision with reason.
  - Antigravity → `continue` decision with reason.
  - DeepSeek → block decision with reason.
    When no checkpoint continuation is required, Antigravity receives the
    provider-defined success response for the native hook and the receiver
    continues to outbox enqueue only for a normalized event.

- Native metadata persistence runs for managed-primary and headless sources when
  native identity is present. Managed descendants retain native identity in their
  event envelope but do not emit native-session-refresh or native-metadata-update
  entries that would replace the owning session's canonical binding.
- Adapter process-kind signals strengthen execution classification. For Claude,
  the background-session kind identifies daemon-owned child execution; marker
  presence remains the authority for TeleClaude lineage.

- The hook input must be a structured payload object; an unstructured
  payload is rejected at the adapter boundary and reported through the
  same best-effort unknown-session path as a malformed payload: an
  error is logged, no error outbox row is enqueued, and the receiver
  exits with a failure status.
- The receiver swallows persistence errors during native-metadata
  writes with a warning log; the hook event itself is still enqueued.
