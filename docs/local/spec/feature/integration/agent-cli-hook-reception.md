---
description: 'Subprocess receiver invoked by agent CLIs that parses a hook payload, resolves a TeleClaude session, and enqueues the event for integration-side processing.'
visibility: 'public'
---

# Agent CLI Hook Reception — Spec

## What it is

The receiver subprocess that an agent CLI invokes for every hook event it
emits (`session_start`, `user_prompt_submit`, `pre_tool_use`, `post_tool_use`,
`agent_stop`, `agent_idle`, `agent_error`, plus event-name variants per agent). It reads the
hook payload from its standard input, selects a per-agent adapter to normalize agent-specific field names, maps the raw
event name to a canonical hook event type, resolves or refreshes a
TeleClaude session identifier from the agent's native session id, and
enqueues the event into the per-session hook outbox. The receiver also
emits adapter-formatted "additional context" on `agent_session_start`
and emits one adapter-formatted response at a control-delivery boundary. The
receiver composes a closed semantic intent — context at a delivery boundary or
a checkpoint continuation reason at stop — while each adapter owns the
event-specific provider wire shape. Control-delivery timing is owned by
`local/projects/teleclaude/spec/feature/agent_runtime/control-delivery`.

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

### Human steering context

At a normalized `user_prompt_submit` boundary carrying prompt text, the receiver
uses the existing runtime-text normalization and shared entry classification to
identify ordinary human spans. A prompt containing such a span receives one
short, transient context cue recalling stewardship, attunement, and leadership.
It reinforces human input as steering (`general/policy/human-contract`).

At session start, the transient provider context carries the person's declared
identity and personalization fields, while excluding per-person credentials,
subscriptions, and runtime overlay settings. At prompt boundaries, human
steering cues come only from ordinary human spans. Recognized wake and
procedure occurrences continue through their existing control-delivery path;
other platform or runtime artifacts do not become new human input.

Peer-only entries, platform controls, reminders, command loaders, runtime
artifacts, and empty prompts receive no human cue. Mixed entries retain their
ordinary human spans for this decision. The cue is composed with any pending
control context into the existing single provider response. It neither edits
the submitted prompt nor prevents its ordinary outbox processing. It creates
no stored control payload, extra model turn, approval gate, or transcript read.

### Command shell context

At session start, when the host shell resolved by the platform's runtime
environment is zsh, the transient provider context for every agent also
carries guidance for writing commands in zsh. Any other host shell adds
nothing. The guidance is owned by `teleclaude/hooks/receiver/_command_shell.py`.

### Use cases

#### UC-R1: Claude session_start with additional context injection

#### UC-R2: Stop hook blocked with checkpoint instruction

#### UC-R3: Codex subagent event dropped pre-resolution

#### UC-R4: System-injected user_prompt_submit dropped

#### UC-R5: Unhandled hook event silently dropped

#### UC-R6: Invalid payload — best-effort error path

#### UC-R7: Receiver runs under the project venv

#### UC-R8: Managed background child retains parent lineage without becoming a session

#### UC-R9: Ambiguous marker-bearing invocation fails closed

#### UC-R10: A person can use one Antigravity conversation with their identity context

```gherkin
Given a person starts an Antigravity conversation in their TeleClaude session
When they continue through model and tool interactions
Then the conversation carries their configured identity context from startup
And later activity remains part of the same conversation
And the session is not reported complete while provider work remains active
```

#### UC-R11: Control context uses each native event's model-facing channel

<!-- planned-change:antigravity-native-subagents-allowed -->

#### UC-R12: Native subagent invocation is blocked in a managed Antigravity session

<!-- change:antigravity-native-subagents-allowed -->

#### UC-R12: A native subagent runs in a managed Antigravity session without taking over its session

<!-- /planned-change:antigravity-native-subagents-allowed -->

### Cross-context references

- Primary home is `agent_runtime` per `docs/local/spec/domain/context-map.md`
  ("Agent CLI hooks reach agent_runtime directly via the receiver IPC").
  This feature is inventoried under `integration` because the receiver
  shares its outbox writer, payload model, and process-boundary plumbing
  with the third-party webhook subsystem.
- Consumes session-map state owned by the `agent_runtime` context
  (sessions and native-session-id mapping).
- Emits checkpoint-seen, native-metadata-update, native-session-refresh,
  agent-session-start, user-prompt-submit, tool-use, agent-stop, agent-idle,
  and agent-error entries into the hook outbox (see `hook-event-outbox`).

## Known caveats

- The cue requires prompt text at the native hook boundary. Claude, Codex, and
  DeepSeek supply it; Antigravity's current hook does not. Antigravity therefore
  relies on the baseline alone rather than guessing human attribution from a
  user-role event or scanning its transcript for this cue.
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
- Codex hooks from provider-native subagent transcripts are discarded before
  session mapping; a child native session id is never associated with its
  managed parent.

<!-- planned-change:antigravity-native-subagents-allowed -->

- Managed Antigravity sessions deny provider-native subagent invocations before
  child execution. Work requiring a child remains available through an
  explicitly dispatched TeleClaude worker.

<!-- change:antigravity-native-subagents-allowed -->

- Antigravity hooks from provider-native subagent executions are discarded
  before session mapping; a subagent's events never take over its managed
  parent's session, and the subagent invocation runs unhindered.

<!-- /planned-change:antigravity-native-subagents-allowed -->

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
