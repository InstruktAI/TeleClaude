---
id: 'project/spec/hook-normalized-events'
type: 'spec'
scope: 'project'
description: 'Canonical normalization, forwarding, and operations contract for agent hook events.'
---

# Hook Normalized Events — Spec

## Purpose

Define, in one place, how raw agent hook events become TeleClaude events, and which events actually enter the durable outbox.

This spec is for both developers and operators.

## Normalized event names

Normalized names are defined in `teleclaude/core/events.py`.

Core names:

- `session_start`
- `user_prompt_submit`
- `after_model`
- `agent_output`
- `agent_stop`
- `notification`
- `session_end`
- `error`

Additional future-facing names also exist (`before_model`, `before_tool`, `after_tool`, etc.) but are not all forwarded.

## Forwarding allowlist (what reaches `hook_outbox`)

The receiver forwards only handled events:

- `session_start`
- `user_prompt_submit`
- `after_model`
- `agent_output`
- `agent_stop`
- `notification`
- `error`

Normalized but not currently forwarded:

- `session_end`
- other normalized pre/post tool scaffolding events outside the allowlist

## Raw event mapping by agent

### Claude mapping

| Raw hook event       | Normalized event     |
| -------------------- | -------------------- |
| `SessionStart`       | `session_start`      |
| `UserPromptSubmit`   | `user_prompt_submit` |
| `PreToolUse`         | `after_model`        |
| `PostToolUse`        | `agent_output`       |
| `PostToolUseFailure` | `agent_output`       |
| `SubagentStart`      | `agent_output`       |
| `SubagentStop`       | `agent_output`       |
| `PermissionRequest`  | `notification`       |
| `Notification`       | `notification`       |
| `Stop`               | `agent_stop`         |
| `SessionEnd`         | `session_end`        |
| `PreCompact`         | `pre_compact`        |

### Gemini mapping

| Raw hook event        | Normalized event        |
| --------------------- | ----------------------- |
| `SessionStart`        | `session_start`         |
| `BeforeAgent`         | `user_prompt_submit`    |
| `AfterAgent`          | `agent_stop`            |
| `BeforeModel`         | `before_model`          |
| `AfterModel`          | `after_model`           |
| `BeforeToolSelection` | `before_tool_selection` |
| `BeforeTool`          | `before_tool`           |
| `AfterTool`           | `agent_output`          |
| `PreCompress`         | `pre_compress`          |
| `Notification`        | `notification`          |
| `SessionEnd`          | `session_end`           |

### Codex mapping

| Raw hook event        | Normalized event |
| --------------------- | ---------------- |
| `agent-turn-complete` | `agent_stop`     |

## Payload normalization contract

Before enqueue, receiver normalization adds TeleClaude fields:

- TeleClaude session id
- source computer name
- normalized event name

When available, native identity is preserved:

- native session id
- native transcript path

Typed payload conversion happens later in daemon dispatch via `build_agent_payload()`.

## Runtime behavior contract

### Delivery model

- Hook events are persisted before processing.
- Delivery is at-least-once.
- Duplicate-safe handlers are required.

### Ordering model

- Outbox fetch is FIFO by creation time.
- Processing is serialized per session to preserve per-session event order.
- Different sessions can process in parallel.

### Failure handling

- Retryable failures use backoff and retry.
- Non-retryable failures are marked delivered-with-error (no infinite loop).
- Invalid payload JSON is marked delivered-with-error immediately.

## Operator checklist for hook incidents

If hook behavior looks wrong:

1. Confirm raw event is mapped to expected normalized event.
2. Confirm normalized event is in forwarding allowlist.
3. Check recent logs for outbox dispatch failures.
4. Check whether failures are retryable or marked delivered-with-error.
5. Restart daemon if outbox worker is unhealthy.

## Change safety checklist

Any hook event change must update all three:

1. Mapping in `teleclaude/core/events.py`
2. Receiver forwarding allowlist in `teleclaude/hooks/receiver.py`
3. This spec
