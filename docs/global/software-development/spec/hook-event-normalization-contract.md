---
id: 'software-development/spec/hook-event-normalization-contract'
type: 'spec'
domain: 'software-development'
scope: 'domain'
description: 'Canonical contract for normalizing external hook events into internal event types and forwarding only handled events.'
---

# Hook Event Normalization Contract — Spec

## What it is

A canonical specification for systems that ingest raw external hook events and convert them into internal events.

It defines:

- how raw events map to normalized internal events,
- which normalized events are forwarded into durable processing,
- and how failures are handled safely.

## Canonical fields

A hook normalization contract must define:

- raw event source namespaces (by provider/tool),
- normalized event names,
- raw -> normalized mapping table,
- forwarding allowlist (what is processed),
- dropped normalized events (what is intentionally ignored),
- payload enrichment fields,
- failure handling (retryable vs non-retryable),
- ordering model and idempotency expectations.

Required payload enrichment fields:

- internal session identifier,
- source identity (for example source host/computer),
- normalized event type,
- native identity fields when available.

## Allowed values

Forwarding status:

- `forwarded`
- `dropped`

Failure category:

- `retryable`
- `non_retryable`
- `invalid_payload`

Ordering model:

- `global_fifo`
- `per_session_serialized`
- `best_effort_parallel`

## Known caveats

- Mapping definitions drift quickly when providers add new raw events. Keep mapping table in lockstep with code.
- Normalized event existence does not imply forwarding; allowlist must be explicit.
- Durable delivery requires idempotent handlers to tolerate retries and partial failures.
