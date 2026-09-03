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
