---
description: 'Cross-computer history. Remote search travels the daemon relay carrying the caller verified identity, so each peer applies its own role band; remote detail and raw retrieval call the remote session_mirrors service directly.'
visibility: 'public'
---

# Cross-Computer History Federation — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md
- @docs/project/spec/domain/context-map.md

## What it is

`telec` is a multi-computer tool: a developer can dispatch agents to remote
boxes. History federation lets an operator search or show sessions across
those boxes without leaving the local terminal. Both `telec history search`
and `telec history show` accept `--computer <name>` (repeatable for search,
single-valued for show). A remote search travels the daemon relay: the CLI
reaches its local daemon, which dispatches a search command to each named
peer carrying the caller's verified email and role, and each peer applies
its own role band before returning rows. A remote detail or raw request
still resolves the computer name to a remote endpoint and calls that
session_mirrors service directly.

For search, all remote calls run in parallel, errors are surfaced per-host,
and the merged result list is re-sorted by `sort_timestamp` descending
before rendering. For show, exactly one computer is allowed and the
request flow is one remote call to either the mirror-detail or the
raw-transcript capability depending on `--raw`.

## Canonical fields

### Use cases

#### Search fan-out across multiple computers

```
Given an operator runs `telec history search <terms> --computer A --computer B`
When the CLI begins remote dispatch
Then the local session_mirrors service is consulted once to resolve A and B to remote endpoints
And the equivalent search request is dispatched to every resolved endpoint in parallel
And local mirrors are NOT included in the merged result
And the merged rows are sorted by sort_timestamp DESC and rendered with a "computer" column
```

#### Per-host error reporting

```
Given one remote search fails (timeout, connection refused, remote error)
When the gathered results are processed
Then a line "[<computer>] Remote search failed: <reason>" is printed
And successful remote results are still rendered
And the empty-result message lists all requested computers if nothing succeeded
```

#### Computer name not in local computer registry

```
Given an operator passes --computer X
And the local session_mirrors service's computer registry does not include X
When the CLI resolves the remote endpoint
Then an error "Computer 'X' not found in local registry" is queued
And the failed host is reported with that error alongside the merged results
```

#### Local resolution failure

```
Given the local session_mirrors service is unreachable when the CLI requests resolution
When the CLI attempts to resolve remote endpoints
Then every requested computer is reported with the same error
  "Failed to resolve remote computers via local session_mirrors service: <reason>"
And no remote search request is issued
```

#### Show enforces single computer

```
Given an operator runs `telec history show S --computer A --computer B`
When the CLI begins remote dispatch
Then it prints "history show accepts exactly one --computer value"
And exits with status code 1 without issuing any remote call
```

#### Show passes through to remote service

```
Given `telec history show S --computer A` and A resolves to a remote endpoint
When the CLI dispatches the show
Then the CLI calls the remote mirror-detail capability (or the raw-transcript capability when --raw)
And on success the returned payload is rendered locally as if the mirror were local
And on transport failure "Failed to fetch session 'S' from A: <reason>" is printed and the CLI exits 1
```

#### UC-CCHF-5: Cross-computer search travels the daemon relay

```
Given a caller searches history on a remote computer
When the search is dispatched
Then the caller's request reaches the local daemon through the authenticated client
And the local daemon dispatches a search command to the remote peer over the daemon relay
And the caller's verified email and role travel with that command
And the remote peer applies its role band before returning rows
And the CLI opens no direct connection to the remote host

Given the remote peer does not carry the search command
Then it answers the unsupported-command error
And the caller is told which computer could not serve the request
```

#### UC-CCHF-6: Remote detail and raw retrieval stay on their current path

```
Given a caller requests a remote mirror's detail or raw transcript
Then the existing remote service call serves it unchanged
And no relay command is required for those paths
```

## Known caveats

- When `--computer` is set, local mirrors on the dispatching host are
  intentionally NOT mixed into the result. There is no "include local"
  toggle; an operator wanting the local results too must run the command
  twice (once with `--computer`, once without).
- Role-scoped access (see `role-scoped-history-access`) does NOT propagate
  to remote computers. Each remote call is evaluated under the remote
  service's own access rules. A non-admin operator can enumerate every
  mirror on a reachable remote.
- The remote request timeout is fixed at five seconds per call. Slow or
  paused remotes produce a transport error without retry.
- The remote search payload omits some local-only columns
  (`conversation_text`, `human_email`, `visibility`); rows are
  reconstructed from the wire payload for sort/render only.
- For show with `--raw`, the remote transcript file is returned in full and
  `--tail` is applied client-side. There is no server-side trimming.
