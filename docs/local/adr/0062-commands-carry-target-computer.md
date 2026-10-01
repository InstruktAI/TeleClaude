---
description: 'Commands carry their target computer and the serialized command is the cross-computer wire format; the parallel Redis command-string vocabulary and per-command remote wrappers are retired.'
date: '2026-07-01'
number: 62
visibility: 'internal'
---

# Commands Carry Target Computer — ADR

## Context

The platform is multi-computer: a session is owned by exactly one computer, and the Redis
transport already provides cross-computer request/response (`send_request`/`read_response`)
plus a generic command dispatcher keyed on `command_type`/`response_mode`. Yet cross-computer
operation was wired for only three verbs (session create, close, keys) through per-command
route wrappers (`dispatch_session_*_to_peer`). Each wrapper flattened a command into a
command **string** and shipped it; the owning computer re-parsed that string back into a
command through a second mapper (`map_redis_input`) that mirrors the real API mapper and
drifts from it — which is why restart, tail, send, unsubscribe, and revive silently executed
locally regardless of the session's owning computer, and why new session verbs were not
forwardable without hand-editing a parallel vocabulary.

The `InternalCommand` model had no notion of a target computer, so the dispatcher had no
routing key. Remote command dispatch was also mixed onto `AdapterClient` (via `_RemoteMixin`),
conflating the UI-adapter facade with the transport.

## Decision

A command declares the computer that owns its target session, and the serialized command is
the single cross-computer wire format:

- `InternalCommand` carries a `computer` field, stamped at the API boundary from the request.
- The dispatcher routes on it: local (or unset) executes in-process; a foreign computer is
  forwarded — the **serialized command** crosses the Redis transport and the owning computer
  reconstructs the identical command and runs it through the same dispatcher and
  `response_mode` layer. Forwarding composes with `response_mode` (`IMMEDIATE` forwards and
  awaits the reply; `FIRE_AND_FORGET` forwards without waiting).
- The parallel command-string vocabulary (`map_redis_input`), the per-command remote wrappers
  (`dispatch_session_*_to_peer`), and the remote-dispatch mixin on `AdapterClient` are retired.
  Remote command dispatch is owned by the transport and driven by the dispatcher;
  `AdapterClient` is concerned with adapters only.

## Consequences

- Every session-scoped operation is computer-addressable for free: adding a command makes it
  forwardable with no transport change, because command serialization is the only crossing
  contract.
- One mapping (the API boundary) and one executor (the shared dispatcher) replace the
  string round-trip; the drift-prone second vocabulary is gone.
- Callers of remote-target operations must supply the owning computer, because a peer-owned
  session has no local row from which to infer it.
- `AdapterClient` no longer holds a transport handle; consumers that reached the transport via
  `client.transport` are re-pointed at the transport owner.

## Alternatives Considered

- **Transparent HTTP reverse-proxy to the peer's API.** Rejected: it re-runs command mapping on
  the remote and ships raw HTTP, adding a second boundary rather than reusing the command the
  origin already built.
- **Keep the command-string vocabulary and extend it to the missing verbs.** Rejected: it
  perpetuates a parallel mapper that mirrors and drifts from the real API, and requires
  per-verb work forever.
