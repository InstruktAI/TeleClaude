---
description: The daemon's shared session projection carries runtime-owned fresh-viewer
  admission and a destination resolved relative to the serving computer.
visibility: internal
---

# Viewer Attachment Projection — Spec

## What it is

The shared daemon API projects the runtime's host-access and selection answer together with
the resolved connection inputs a consumer needs to render a session viewer.
The destination is relative to the daemon serving the consumer, including
when the session record originated on a peer. An unresolved destination stays
unresolved until the daemon has its connection inputs.

Runtime admission is owned by
`local/projects/teleclaude/spec/feature/agent_runtime/host-pane-access`.
Integration translates it and the daemon's computer registry through the
shared session DTO projection, following `sdlc/policy/domain-ownership`.
The projection's eligibility, ordering, and connection lifecycle remain owned
by `local/projects/teleclaude/design/architecture/api-server`.

## Canonical fields

Session API types own the additive access/selection and structured destination
representation. The destination carries the resolved connection inputs, not
an executable shell command. HTTP session reads and the session stream use the
same projection. Runtime and integration remain the owners of the facts;
clients consume the provided answer.

### Use cases

#### UC-VAP1: Session reads and streams agree on attachment facts

#### UC-VAP2: Resolved destination changes reach the existing session stream

## Known caveats

Consumers that do not understand the additive attachment fields retain their
existing behavior. A consumer requiring those fields treats their absence as
unresolved access and is activated together with its updated serving daemon.
