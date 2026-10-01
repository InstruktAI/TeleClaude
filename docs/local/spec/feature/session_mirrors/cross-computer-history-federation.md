---
description: 'Cross-computer history. Remote search travels the daemon relay carrying the caller verified identity, so each peer applies its own role band; remote detail and raw retrieval travel the same relay, so the peer answers them within its own history scope.'
visibility: 'public'
---

# Cross-Computer History Federation — Spec

## Required reads

- @docs/local/spec/domain/session_mirrors.md
- @docs/local/spec/domain/context-map.md

## What it is

`telec` is a multi-computer tool: a developer can dispatch agents to remote
boxes. History federation lets an operator search or show sessions across
those boxes without leaving the local terminal. Both `telec history search`
and `telec history show` accept `--computer <name>` (repeatable for search,
single-valued for show). A remote search travels the daemon relay: the CLI
reaches its local daemon, which dispatches a search command to each named
peer carrying the caller's verified identity as its principal, and each
peer resolves that principal against its own people registry and applies its
own history scope before returning rows. A remote detail or raw request
travels the same relay: the local daemon dispatches a history detail command
to the named peer carrying the caller's verified identity, and the peer
answers from its own history detail capability within its history scope for
that identity.

For search, all remote calls run in parallel, errors are surfaced per-host,
and the merged result list is re-sorted by `sort_timestamp` descending
before rendering. For show, exactly one computer is allowed and the
request flow is one relayed detail command, which carries `--raw` to the
peer.

## Canonical fields

### Use cases

#### Search fan-out across multiple computers

```
Given an operator runs `telec history search <terms> --computer A --computer B`
When the search is dispatched
Then the CLI issues one authenticated request to its local daemon
And the local daemon dispatches a search command to A and to B over the daemon relay, in parallel
And the caller's verified identity travels with each command, so each peer applies its own history scope
And local mirrors are NOT included in the merged result
And the merged rows are sorted by sort_timestamp DESC and rendered with a "computer" column
```

#### Per-host error reporting

```
Given one remote search fails (relay timeout, unreachable peer, remote error, or a peer that does not carry the search command)
When the gathered results are processed
Then a line "[<computer>] Remote search failed: <reason>" is printed
And successful remote results are still rendered
And the empty-result message lists all requested computers if nothing succeeded
```

#### Show enforces single computer

```
Given an operator runs `telec history show S --computer A --computer B`
When the CLI begins remote dispatch
Then it prints "history show accepts exactly one --computer value"
And exits with status code 1 without issuing any remote call
```

#### UC-CCHF-5: Cross-computer search travels the daemon relay

```
Given a caller searches history on a remote computer
When the search is dispatched
Then the caller's request reaches the local daemon through the authenticated client
And the local daemon dispatches a search command to the remote peer over the daemon relay
And the caller's verified identity travels with that command as its principal
And the remote peer resolves a person's role from its own people registry, never from a role the command carries
And the remote peer applies its history scope to that identity before returning rows
And a peer that receives a command carrying no identity refuses it rather than answering unscoped
And the CLI opens no direct connection to the remote host

Given the remote peer does not carry the search command
Then it answers the unsupported-command error
And the caller is told which computer could not serve the request
```

#### UC-CCHF-7: Remote show travels the daemon relay

```
Given a caller runs `telec history show <session-id> --computer <peer>`, with or without `--raw`
When the show is dispatched
Then the caller's request reaches the local daemon through the authenticated client
And the local daemon dispatches a history detail command to the peer over the daemon relay
And the caller's verified identity travels with that command as its principal
And the peer answers from its own history detail capability, within its history scope for that identity
And the CLI renders the peer's answer as it renders a local one
And the CLI opens no direct connection to the peer

Given the peer holds no conversation for that identifier within the caller's scope
Then the CLI reports "No transcript found for session '<session-id>'" and exits non-zero

Given the relay cannot complete the request (timeout, unreachable peer, peer error, or a peer that does not carry the detail command)
Then the CLI reports "Failed to fetch session '<session-id>' from <peer>: <reason>" and exits non-zero
```

## Known caveats

- When `--computer` is set, local mirrors on the dispatching host are
  intentionally NOT mixed into the result. There is no "include local"
  toggle; an operator wanting the local results too must run the command
  twice (once with `--computer`, once without).
- Role-scoped access propagates for search and show: the caller's verified
  identity travels with the relay command, and each peer applies its own
  history scope before answering. A peer decides a person's role from its own
  people registry; a role carried in the command is never an authorization
  input.
- A remote request waits a bounded time for the peer's relay answer. A slow
  or paused peer produces a timeout failure without retry.
- The remote search payload omits some local-only columns
  (`conversation_text`, `human_email`, `visibility`); rows are
  reconstructed from the wire payload for sort/render only.
- For show with `--raw`, the peer's transcript answer is printed whole. No
  cut is applied on either side.
