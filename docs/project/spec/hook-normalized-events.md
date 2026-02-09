---
id: 'project/spec/hook-normalized-events'
type: 'spec'
scope: 'project'
description: 'Canonical TeleClaude hook normalization and forwarding contract for project runtime behavior.'
---

# Hook Normalized Events — Spec

## What it is

Project-specific contract for how TeleClaude normalizes raw hook events and forwards only handled event types into durable outbox processing.

## Canonical fields

This spec must define:

- raw event source namespaces,
- normalized event names,
- raw-to-normalized mapping,
- forwarding allowlist,
- dropped normalized events,
- payload enrichment fields,
- failure handling model,
- ordering model.

Required payload enrichment fields:

- TeleClaude session id,
- source computer,
- normalized event type,
- native identity fields when present.

## Allowed values

Forwarding status:

- `forwarded`
- `dropped`

Failure class:

- `retryable`
- `non_retryable`
- `invalid_payload`

Ordering mode:

- `per_session_serialized`

## Known caveats

- A normalized event may still be dropped if not in forwarding allowlist.
- Mapping changes must stay in sync with receiver and event definition code.
- Handler logic must remain idempotent because delivery is at-least-once.
