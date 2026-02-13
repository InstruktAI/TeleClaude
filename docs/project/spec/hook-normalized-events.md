---
id: 'project/spec/hook-normalized-events'
type: 'spec'
scope: 'project'
description: 'Plain-language contract for how TeleClaude maps raw hook events and decides what gets processed.'
---

# Hook Normalized Events — Spec

## What it is

This file explains one thing clearly:

- raw hook events come in from agents,
- TeleClaude maps them to internal names,
- only some of those internal names are actually forwarded for processing.

Use it when:

- an event "exists" but seems ignored,
- hook behavior differs across Claude/Gemini/Codex,
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
  - mint new id only at explicit adoption points:
    - `session_start` (all agents),
    - `agent_stop` (Codex only).
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
- Delivery is at-least-once; handlers must stay idempotent.
