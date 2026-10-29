---
description: 'Plain-language contract for how TeleClaude maps raw hook events and decides what gets processed.'
visibility: 'public'
---

# Hook Normalized Events — Spec

## What it is

This file explains one thing clearly:

- raw hook events come in from agents,
- TeleClaude maps them to internal names,
- only some of those internal names are actually forwarded for processing.

Use it when:

- an event "exists" but seems ignored,
- hook behavior differs across Claude/Antigravity/Codex/DeepSeek,
- you are adding/changing hook mappings.

## Canonical fields

This spec must always document:

- raw event sources (per agent/tool),
- normalized internal event names,
- raw -> normalized mapping,
- forwarding allowlist (processed events),
- dropped normalized events (intentionally ignored),
- payload fields added by receiver,
- failure handling class,
- ordering model.

Current raw-to-normalized lifecycle mapping:

<!-- planned-change:antigravity-native-subagents-allowed -->

| Agent       | Raw event and condition                                                                                                                                            | Normalized event     | Forwarding |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------- | ---------- |
| Claude      | `SessionStart`                                                                                                                                                     | `session_start`      | forwarded  |
| Claude      | `UserPromptSubmit`                                                                                                                                                 | `user_prompt_submit` | forwarded  |
| Claude      | `PreToolUse`                                                                                                                                                       | `pre_tool_use`       | forwarded  |
| Claude      | `Notification` where `notification_type` is `permission_prompt`, `agent_needs_input`, `elicitation_dialog`, `elicitation_url_dialog`, or `quota_auto_resume_stale` | `agent_blocked`      | forwarded  |
| Claude      | `Notification` where `notification_type` is `quota_auto_resume_disabled`                                                                                           | `agent_turn_failed`  | forwarded  |
| Claude      | `Notification` with any other `notification_type`, recognized or not                                                                                               | (none)               | dropped    |
| Claude      | `PostToolUse`                                                                                                                                                      | `post_tool_use`      | forwarded  |
| Claude      | `PostToolUseFailure`                                                                                                                                               | `post_tool_use`      | forwarded  |
| Claude      | `PostToolBatch`                                                                                                                                                    | `post_tool_use`      | forwarded  |
| Claude      | `Stop`                                                                                                                                                             | `agent_stop`         | forwarded  |
| Claude      | `StopFailure`                                                                                                                                                      | `agent_turn_failed`  | forwarded  |
| Claude      | `PostCompact` where `trigger == manual`                                                                                                                            | `agent_idle`         | forwarded  |
| Claude      | `PostCompact` where `trigger == auto`                                                                                                                              | (none)               | dropped    |
| Antigravity | `PreInvocation` where `invocationNum == 0`                                                                                                                         | `session_start`      | forwarded  |
| Antigravity | `PreInvocation` where `invocationNum > 0` and latest transcript role is `user`                                                                                     | `user_prompt_submit` | forwarded  |
| Antigravity | `PreInvocation` where `invocationNum > 0` and no prompt boundary is present                                                                                        | (none)               | dropped    |
| Antigravity | `PreToolUse` for a native subagent invocation from a managed source                                                                                                | (none)               | dropped    |
| Antigravity | Other `PreToolUse` invocations                                                                                                                                     | `pre_tool_use`       | forwarded  |
| Antigravity | `PostToolUse`                                                                                                                                                      | `post_tool_use`      | forwarded  |
| Antigravity | `PostInvocation`                                                                                                                                                   | `post_tool_use`      | forwarded  |
| Antigravity | `Stop` where `error` is a non-empty string                                                                                                                         | `agent_turn_failed`  | forwarded  |
| Antigravity | `Stop` where `error` is empty and `fullyIdle == false`                                                                                                             | (none)               | dropped    |
| Antigravity | `Stop` where `error` is empty and `fullyIdle == true`                                                                                                              | `agent_stop`         | forwarded  |
| Codex       | `SessionStart`                                                                                                                                                     | `session_start`      | forwarded  |
| Codex       | `UserPromptSubmit`                                                                                                                                                 | `user_prompt_submit` | forwarded  |
| Codex       | `PreToolUse`                                                                                                                                                       | `pre_tool_use`       | forwarded  |
| Codex       | `PermissionRequest`                                                                                                                                                | `agent_blocked`      | forwarded  |
| Codex       | `PostToolUse`                                                                                                                                                      | `post_tool_use`      | forwarded  |
| Codex       | `Stop`                                                                                                                                                             | `agent_stop`         | forwarded  |
| Codex       | `PostCompact` where `trigger == manual`                                                                                                                            | `agent_idle`         | forwarded  |
| Codex       | `PostCompact` where `trigger == auto`                                                                                                                              | (none)               | dropped    |
| DeepSeek    | `SessionStart`                                                                                                                                                     | `session_start`      | forwarded  |
| DeepSeek    | `UserPromptSubmit`                                                                                                                                                 | `user_prompt_submit` | forwarded  |
| DeepSeek    | `PreToolUse`                                                                                                                                                       | `pre_tool_use`       | forwarded  |
| DeepSeek    | `PostToolUse`                                                                                                                                                      | `post_tool_use`      | forwarded  |
| DeepSeek    | `PostToolUseFailure`                                                                                                                                               | `post_tool_use`      | forwarded  |
| DeepSeek    | `PostToolBatch`                                                                                                                                                    | `post_tool_use`      | forwarded  |
| DeepSeek    | `Stop`                                                                                                                                                             | `agent_stop`         | forwarded  |
| DeepSeek    | `StopFailure`                                                                                                                                                      | `agent_turn_failed`  | forwarded  |

<!-- change:antigravity-native-subagents-allowed -->

| Agent       | Raw event and condition                                                                                                                                            | Normalized event                                 | Forwarding |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------ | ---------- |
| Claude      | `SessionStart`                                                                                                                                                     | `session_start`                                  | forwarded  |
| Claude      | `UserPromptSubmit`                                                                                                                                                 | `user_prompt_submit`                             | forwarded  |
| Claude      | `PreToolUse`                                                                                                                                                       | `pre_tool_use`                                   | forwarded  |
| Claude      | `Notification` where `notification_type` is `permission_prompt`, `agent_needs_input`, `elicitation_dialog`, `elicitation_url_dialog`, or `quota_auto_resume_stale` | `agent_blocked`                                  | forwarded  |
| Claude      | `Notification` where `notification_type` is `quota_auto_resume_disabled`                                                                                           | `agent_turn_failed`                              | forwarded  |
| Claude      | `Notification` with any other `notification_type`, recognized or not                                                                                               | (none)                                           | dropped    |
| Claude      | `PostToolUse`                                                                                                                                                      | `post_tool_use`                                  | forwarded  |
| Claude      | `PostToolUseFailure`                                                                                                                                               | `post_tool_use`                                  | forwarded  |
| Claude      | `PostToolBatch`                                                                                                                                                    | `post_tool_use`                                  | forwarded  |
| Claude      | `Stop`                                                                                                                                                             | `agent_stop`                                     | forwarded  |
| Claude      | `StopFailure`                                                                                                                                                      | `agent_turn_failed`                              | forwarded  |
| Claude      | `PostCompact` where `trigger == manual`                                                                                                                            | `agent_idle`                                     | forwarded  |
| Claude      | `PostCompact` where `trigger == auto`                                                                                                                              | (none)                                           | dropped    |
| Antigravity | `PreInvocation` where `invocationNum == 0`                                                                                                                         | `session_start`                                  | forwarded  |
| Antigravity | `PreInvocation` where `invocationNum > 0` and latest transcript role is `user`                                                                                     | `user_prompt_submit`                             | forwarded  |
| Antigravity | `PreInvocation` where `invocationNum > 0` and no prompt boundary is present                                                                                        | (none)                                           | dropped    |
| Antigravity | `Stop` from a provider-native subagent's execution where `fullyIdle == true`                                                                                       | `agent_stop` of the subagent's root conversation | forwarded  |
| Antigravity | Every other hook from a provider-native subagent's execution                                                                                                       | (none)                                           | dropped    |
| Antigravity | Other `PreToolUse` invocations                                                                                                                                     | `pre_tool_use`                                   | forwarded  |
| Antigravity | `PostToolUse`                                                                                                                                                      | `post_tool_use`                                  | forwarded  |
| Antigravity | `PostInvocation`                                                                                                                                                   | `post_tool_use`                                  | forwarded  |
| Antigravity | `Stop` where `error` is a non-empty string                                                                                                                         | `agent_turn_failed`                              | forwarded  |
| Antigravity | `Stop` where `error` is empty and `fullyIdle == false`                                                                                                             | (none)                                           | dropped    |
| Antigravity | `Stop` where `error` is empty and `fullyIdle == true`                                                                                                              | `agent_stop`                                     | forwarded  |
| Codex       | `SessionStart`                                                                                                                                                     | `session_start`                                  | forwarded  |
| Codex       | `UserPromptSubmit`                                                                                                                                                 | `user_prompt_submit`                             | forwarded  |
| Codex       | `PreToolUse`                                                                                                                                                       | `pre_tool_use`                                   | forwarded  |
| Codex       | `PermissionRequest`                                                                                                                                                | `agent_blocked`                                  | forwarded  |
| Codex       | `PostToolUse`                                                                                                                                                      | `post_tool_use`                                  | forwarded  |
| Codex       | `Stop`                                                                                                                                                             | `agent_stop`                                     | forwarded  |
| Codex       | `PostCompact` where `trigger == manual`                                                                                                                            | `agent_idle`                                     | forwarded  |
| Codex       | `PostCompact` where `trigger == auto`                                                                                                                              | (none)                                           | dropped    |
| DeepSeek    | `SessionStart`                                                                                                                                                     | `session_start`                                  | forwarded  |
| DeepSeek    | `UserPromptSubmit`                                                                                                                                                 | `user_prompt_submit`                             | forwarded  |
| DeepSeek    | `PreToolUse`                                                                                                                                                       | `pre_tool_use`                                   | forwarded  |
| DeepSeek    | `PostToolUse`                                                                                                                                                      | `post_tool_use`                                  | forwarded  |
| DeepSeek    | `PostToolUseFailure`                                                                                                                                               | `post_tool_use`                                  | forwarded  |
| DeepSeek    | `PostToolBatch`                                                                                                                                                    | `post_tool_use`                                  | forwarded  |
| DeepSeek    | `Stop`                                                                                                                                                             | `agent_stop`                                     | forwarded  |
| DeepSeek    | `StopFailure`                                                                                                                                                      | `agent_turn_failed`                              | forwarded  |

<!-- /planned-change:antigravity-native-subagents-allowed -->

Tool-call closure. Every tool event carries the provider's own identifier for
the call — `tool_use_id` for Claude, Codex, and DeepSeek, `stepIdx` for
Antigravity — normalized as one tool-call identifier, so parallel calls open
and close individually. Each `post_tool_use` source above closes as follows:

| Agent       | Raw event            | Closes                                      |
| ----------- | -------------------- | ------------------------------------------- |
| Claude      | `PostToolUse`        | the identified call (returned)              |
| Claude      | `PostToolUseFailure` | the identified call (failed)                |
| Claude      | `PostToolBatch`      | every open call (batch resolved)            |
| Codex       | `PostToolUse`        | the identified call (any result)            |
| DeepSeek    | `PostToolUse`        | the identified call (returned)              |
| DeepSeek    | `PostToolUseFailure` | the identified call (failed)                |
| DeepSeek    | `PostToolBatch`      | every open call (batch resolved)            |
| Antigravity | `PostToolUse`        | the identified call (any result)            |
| Antigravity | `PostInvocation`     | nothing; it carries no tool-call identifier |

A `post_tool_use` without a tool-call identifier and without batch resolution
is activity only. A runtime that reports a call's start but never its end
leaves that call open until the turn ends. The hook outbox delivers tool
events losslessly.

`agent_blocked` and `agent_turn_failed` are the distress vocabulary: a session
waiting on an approval or input decision it cannot resolve itself, and a turn
terminated by a runtime or provider failure. Coverage is whatever each provider
natively exposes — a provider with no native signal for a kind produces no
normalized event of that kind, and no substitute is inferred from adjacent
events.

`agent_blocked` names a state the session is in, never a decision it is about
to take. For Claude the waiting state is `Notification`, whose
`notification_type` names the cause; its `PermissionRequest` is the pre-prompt
decision hook, fires for calls a hook may still allow without any prompt, and
is therefore not installed for this purpose. Codex exposes no notification
hook, and its `PermissionRequest` fires only for calls that actually require
approval; TeleClaude installs no decision on it, so an observed occurrence is
an approval the session cannot resolve itself.

Antigravity carries both terminal outcomes on the already-installed `Stop`
event rather than a dedicated one, and its conditions above are mutually
exclusive and exhaustive. A non-empty `error` member is the failure signal the
provider designates ("present if stopped due to error") and is tested first.
Otherwise `fullyIdle` decides: a stop that is not idle is dropped, and an idle
stop is the turn's completion.

<!-- planned:antigravity-native-subagents-allowed -->

Hooks from a provider-native subagent's execution, recognized as
`local/projects/teleclaude/spec/feature/integration/agent-cli-hook-reception`
states, are dropped before session resolution, so none of them becomes the
identity, status or transcript of any session
(`local/projects/teleclaude/spec/session-identity-truth`). The one exception is
a subagent's `Stop` with `fullyIdle == true`: it is forwarded as the
`agent_stop` of the subagent's root conversation, the one at the top of its
invocation chain, carrying that conversation's identity and none of the
subagent's, and it never reports a failure.

<!-- /planned:antigravity-native-subagents-allowed -->

`terminationReason` is carried as native evidence and is never gated. It names
why the loop ended in the provider's executor vocabulary, which the provider
neither documents nor stabilizes; the Antigravity hook document records the
observed values. Deciding completion from that vocabulary would announce a
clean stop as a failure whenever a value is unrecognized, so the platform
reads the two members the provider designates and leaves the reason to the
recipient intelligence.

**One terminal outcome per turn.** Every provider emits at most one of
turn-end and turn-failure for a given turn, so the two never both account for
one turn: Claude fires `StopFailure` in place of `Stop`; Antigravity resolves
one `Stop` through the branch above; Codex exposes no failure signal; and on
the DeepSeek Harness the error path raises past the turn-stopping dispatch that
produces `Stop`. Consumers still treat the outcome as a single slot rather than
relying on that exclusivity.

Claude's `Notification` is a multi-purpose carrier whose `notification_type`
discriminates the cause, so the platform admits subtypes by allowlist: an
admitted subtype maps to the distress kind its cause already matches, and every
other subtype — recognized or not — is dropped. A subtype earns admission only
by naming a state from which no turn outcome is coming; one that restates an
outcome the platform has already published carries no information, which is why
`idle_prompt` is not admitted. A usage-limit wait that will not self-resume is
the same waiting state as an approval wait and normalizes to `agent_blocked`;
a usage-limit wait the runtime abandons ended the turn without completing it and
normalizes to `agent_turn_failed`. Native subtype and the provider's own message
text ride along as evidence, so the recipient intelligence reads the cause
without inspecting the emitting session, and no code grades that text.

The emitting child's notification hook is an observation source, not a context
injection or permission-decision boundary. Parent delivery uses the existing
control-delivery surface and the recipient's own eligible runtime boundaries.
No provider is assigned a hook it does not expose.

No provider normalizes to `error`. That event is the platform's internal error
channel — receiver faults and agent-restart faults — and carries no provider
turn state.

Conditional mappings are evaluated against the provider payload before session
resolution or any receiver side effect. A condition that does not match produces
no normalized event and returns that hook's provider-defined neutral response.
Agent hook installers preserve native event names in receiver commands; only the
receiver owns normalization.

Each adapter owns one manifest containing only the native events TeleClaude
installs and ingests for that provider. The manifest is the implementation
source for normalization, control-delivery eligibility, session minting, and
installer registration. Complete provider vocabularies and stdout contracts
remain in the consolidated third-party documentation; unused provider events
are not repeated as `None` mappings or installer cleanup catalogs in runtime
code. Installer reconciliation removes identifiable TeleClaude receiver
commands from list-shaped hook blocks that are no longer declared. Opaque or
malformed provider-owned values are preserved because their ownership cannot be
established; a declared event is replaced with TeleClaude's valid list shape
during merge.

### Managed ordinary launch context

The receiver carries the runtime-owned ordinary launch context from its child
environment unchanged through normalization and the durable hook outbox.
Compaction keeps its separate maintenance launch context. Correlation is not
session authorization: existing session resolution and descendant filtering
retain their contracts. The runtime decides applicability and readiness under
`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`.

### Maintenance launch context

A temporary compaction launch supplies immutable attempt context through its
child-process startup environment. Its managed hook subprocesses inherit that
context, and the receiver captures it at startup and carries it unchanged in
the normalized internal event envelope. The provider's native event names and
payload semantics, installed hook commands and hook trust state remain
unchanged. Ordinary launches carry no maintenance context.

The agent-runtime consumer owns matching that context to its active attempt.
Maintenance startup opens only that attempt's readiness, and maintenance
completion settles only that attempt. Events from an abandoned or superseded
attempt do not update the ordinary conversation's readiness, status or close
state and do not wake its pending control input. The receiver transports these
coordination facts; it decides no compaction lifecycle policy.

Receiver-added payload fields:

- TeleClaude session id,
- source computer,
- normalized event type,
- optional native identity fields when available (`native_session_id`, `native_log_file`).
- for `agent_blocked`, the adapter's normalization reason, which tells a
  usage-limit wait apart from a wait on an approval or answer, so consumers
  never read provider subtypes to learn which one it is.

Important: native identity fields are **optional**, not required.

Identity gating rule:

- Non-headless (TMUX) route:
  - `TMPDIR/teleclaude_session_id` is authoritative.
  - map/DB lookup is not used.
  - missing/empty marker is a contract violation.
- Headless route:
  - resolve via native mapping (`agent:native_session_id`) then DB lookup by `native_session_id`.
  - mint new id only at the adapter manifest's explicit adoption points; the
    current providers adopt on `session_start` and `agent_stop`.
  - if a handled event cannot resolve session id, fail fast as contract violation.

## Allowed values

Forwarding status:

- `forwarded`
- `dropped`

Failure class:

- `retryable`
- `non_retryable`
- `invalid_payload`

Ordering model:

- `per_session_serialized`

## Known caveats

- A normalized event can still be dropped if it is not in forwarding allowlist.
- Forwarded event types are not silently dropped on identity failure; receiver exits nonzero for contract violations.
- Mapping changes in code must be reflected here immediately.
- `SubagentStop` is not a TeleClaude manifest event for any provider and is
  never installed as a TeleClaude receiver hook. Provider-owned or static
  safety hooks remain outside this mapping contract.
- Delivery is at-least-once; handlers must stay idempotent.

## See Also

- docs/local/spec/feature/agent_runtime/session-input-delivery.md — startup input readiness is separate from normalized lifecycle activation.

<!-- planned:antigravity-native-subagents-allowed -->

- docs/third-party/antigravity-cli/sub-agents.md — the observed Antigravity subagent records and idle reporting that subagent hook handling rests on.

<!-- /planned:antigravity-native-subagents-allowed -->
