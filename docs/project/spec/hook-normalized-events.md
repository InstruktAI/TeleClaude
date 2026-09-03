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

<!-- planned-change:session-distress-ingestion -->
| Agent       | Raw event and condition                                                        | Normalized event     | Forwarding |
| ----------- | ------------------------------------------------------------------------------ | -------------------- | ---------- |
| Claude      | `SessionStart`                                                                 | `session_start`      | forwarded  |
| Claude      | `UserPromptSubmit`                                                             | `user_prompt_submit` | forwarded  |
| Claude      | `PreToolUse`                                                                   | `pre_tool_use`       | forwarded  |
| Claude      | `PostToolUse`                                                                  | `post_tool_use`      | forwarded  |
| Claude      | `Stop`                                                                         | `agent_stop`         | forwarded  |
| Claude      | `PostCompact` where `trigger == manual`                                        | `agent_idle`          | forwarded  |
| Claude      | `PostCompact` where `trigger == auto`                                          | (none)                | dropped    |
| Antigravity | `PreInvocation` where `invocationNum == 0`                                     | `session_start`      | forwarded  |
| Antigravity | `PreInvocation` where `invocationNum > 0` and latest transcript role is `user` | `user_prompt_submit` | forwarded  |
| Antigravity | `PreInvocation` where `invocationNum > 0` and no prompt boundary is present    | (none)               | dropped    |
| Antigravity | `PreToolUse`                                                                   | `pre_tool_use`       | forwarded  |
| Antigravity | `PostInvocation`                                                               | `post_tool_use`      | forwarded  |
| Antigravity | `Stop` where `fullyIdle == true`                                               | `agent_stop`         | forwarded  |
| Antigravity | `Stop` where `fullyIdle == false`                                              | (none)               | dropped    |
| Codex       | `SessionStart`                                                                 | `session_start`      | forwarded  |
| Codex       | `UserPromptSubmit`                                                             | `user_prompt_submit` | forwarded  |
| Codex       | `PreToolUse`                                                                   | `pre_tool_use`       | forwarded  |
| Codex       | `PostToolUse`                                                                  | `post_tool_use`      | forwarded  |
| Codex       | `Stop`                                                                         | `agent_stop`         | forwarded  |
| DeepSeek    | `SessionStart`                                                                 | `session_start`      | forwarded  |
| DeepSeek    | `UserPromptSubmit`                                                             | `user_prompt_submit` | forwarded  |
| DeepSeek    | `PreToolUse`                                                                   | `pre_tool_use`       | forwarded  |
| DeepSeek    | `PostToolUse`                                                                  | `post_tool_use`      | forwarded  |
| DeepSeek    | `Stop`                                                                         | `agent_stop`         | forwarded  |
| DeepSeek    | `StopFailure`                                                                  | `error`              | forwarded  |
<!-- change:session-distress-ingestion -->
| Agent | Raw event and condition | Normalized event | Forwarding |
| ----- | ----------------------- | ---------------- | ---------- |
| Claude | `SessionStart` | `session_start` | forwarded |
| Claude | `UserPromptSubmit` | `user_prompt_submit` | forwarded |
| Claude | `PreToolUse` | `pre_tool_use` | forwarded |
| Claude | `Notification` where `notification_type` is `permission_prompt`, `agent_needs_input`, `elicitation_dialog`, or `elicitation_url_dialog` | `agent_blocked` | forwarded |
| Claude | `Notification` with any other `notification_type` | (none) | dropped |
| Claude | `PostToolUse` | `post_tool_use` | forwarded |
| Claude | `Stop` | `agent_stop` | forwarded |
| Claude | `StopFailure` | `agent_turn_failed` | forwarded |
| Claude | `PostCompact` where `trigger == manual` | `agent_idle` | forwarded |
| Claude | `PostCompact` where `trigger == auto` | (none) | dropped |
| Antigravity | `PreInvocation` where `invocationNum == 0` | `session_start` | forwarded |
| Antigravity | `PreInvocation` where `invocationNum > 0` and latest transcript role is `user` | `user_prompt_submit` | forwarded |
| Antigravity | `PreInvocation` where `invocationNum > 0` and no prompt boundary is present | (none) | dropped |
| Antigravity | `PreToolUse` | `pre_tool_use` | forwarded |
| Antigravity | `PostInvocation` | `post_tool_use` | forwarded |
| Antigravity | `Stop` where `terminationReason == "error"` | `agent_turn_failed` | forwarded |
| Antigravity | `Stop` where `terminationReason != "error"` and `fullyIdle == true` | `agent_stop` | forwarded |
| Antigravity | `Stop` where `terminationReason != "error"` and `fullyIdle == false` | (none) | dropped |
| Codex | `SessionStart` | `session_start` | forwarded |
| Codex | `UserPromptSubmit` | `user_prompt_submit` | forwarded |
| Codex | `PreToolUse` | `pre_tool_use` | forwarded |
| Codex | `PermissionRequest` | `agent_blocked` | forwarded |
| Codex | `PostToolUse` | `post_tool_use` | forwarded |
| Codex | `Stop` | `agent_stop` | forwarded |
| DeepSeek | `SessionStart` | `session_start` | forwarded |
| DeepSeek | `UserPromptSubmit` | `user_prompt_submit` | forwarded |
| DeepSeek | `PreToolUse` | `pre_tool_use` | forwarded |
| DeepSeek | `PostToolUse` | `post_tool_use` | forwarded |
| DeepSeek | `Stop` | `agent_stop` | forwarded |
| DeepSeek | `StopFailure` | `agent_turn_failed` | forwarded |

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
event rather than a dedicated one. `terminationReason` is the discriminator,
taking `model_stop`, `max_steps_exceeded`, and `error` among its values; the
sibling `error` member is an empty string on the normal path, so its presence
does not distinguish a failure. The three `Stop` conditions above are mutually
exclusive and exhaustive.

**One terminal outcome per turn.** Every provider emits at most one of
turn-end and turn-failure for a given turn, so the two never both account for
one turn: Claude fires `StopFailure` in place of `Stop`; Antigravity resolves
one `Stop` through the branch above; Codex exposes no failure signal; and on
the DeepSeek Harness the error path raises past the turn-stopping dispatch that
produces `Stop`. Consumers still treat the outcome as a single slot rather than
relying on that exclusivity.

No provider normalizes to `error`. That event is the platform's internal error
channel — receiver faults and agent-restart faults — and carries no provider
turn state.
<!-- /planned-change:session-distress-ingestion -->

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

Receiver-added payload fields:

- TeleClaude session id,
- source computer,
- normalized event type,
- optional native identity fields when available (`native_session_id`, `native_log_file`).

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
