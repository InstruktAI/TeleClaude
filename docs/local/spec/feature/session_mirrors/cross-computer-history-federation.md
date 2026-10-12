---
description: 'Cross-computer history. Search fans out to the named computers in parallel and merges their rows; show reads exactly one named computer; each computer that fails is reported by name.'
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
single-valued for show). A request naming another computer runs on that
computer (`local/projects/teleclaude/spec/feature/integration/computer-addressed-execution`),
which answers it within the caller's reach there
(`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`).

For search, all remote calls run in parallel, errors are surfaced per-host,
and the merged result list is re-sorted by `sort_timestamp` descending
before rendering. For show, exactly one computer is allowed.

## Canonical fields

### Use cases

#### Search fan-out across multiple computers

```
Given an operator runs `telec history search <terms> --computer A --computer B`
When the search is dispatched
Then the search is sent to A and to B in parallel
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

#### UC-CCHF-7: Remote show renders the peer's answer and names its failures

```
Given a caller runs `telec history show <session-id> --computer <peer>`, with or without `--raw`
When the show is dispatched
Then the CLI renders the peer's answer as it renders a local one

Given the peer holds no conversation for that identifier within the caller's scope
Then the CLI reports "No transcript found for session '<session-id>'" and exits non-zero

Given the relay cannot complete the request (timeout, unreachable peer, peer error, or a peer that does not carry the detail command)
Then the CLI reports "Failed to fetch session '<session-id>' from <peer>: <reason>" and exits non-zero
```

## Known caveats

- When `--computer` is set, only the named computers are searched: local
  mirrors on the dispatching host are included only when its own name is among
  them. There is no "include local" toggle; an operator wanting the local
  results beside remote ones names the local computer too, or runs the command
  twice (once with `--computer`, once without).
- A remote request waits a bounded time for the peer's relay answer. A slow
  or paused peer produces a timeout failure without retry.
- The remote search payload omits some local-only columns
  (`conversation_text`, `human_email`, `visibility`); rows are
  reconstructed from the wire payload for sort/render only.
- For show with `--raw`, the peer's transcript answer is printed whole. No
  cut is applied on either side.
