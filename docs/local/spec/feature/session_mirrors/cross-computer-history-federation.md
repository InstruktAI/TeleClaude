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
before rendering. For show, exactly one computer is allowed; a request naming
multiple computers is refused before any remote call.

<!-- planned:history-search-all-computers -->

`all` is the reserved value of `--computer` that names every computer in the
fleet roster `telec computers list` reports, this computer included. A search
naming `all` searches this computer and every computer the roster lists
online, exactly as a search naming each of them would. A computer the roster
lists offline is reported as not searched, with that reason, and no request is
sent to it. `all` stands alone: a search naming it beside another computer is
refused before any computer is searched. For show, `all` names more than one
computer and is refused like any other such request. At the CLI edge, a search
naming `all` is cleared for this computer as a local search is, and for the
other computers as a search naming them is
(`local/projects/teleclaude/spec/feature/identity/command-clearance`).
<!-- /planned:history-search-all-computers -->

## Canonical fields

### Use cases

#### UC-CCHF-8: An operator searches history across selected computers

```
Scenario: Search conversations across the selected computers
  Given an operator requests history from computers A and B
  When they run `telec history search <terms> --computer A --computer B`
  Then matching conversations from the selected computers appear in one result list
  And each result identifies its computer
  And local results appear only when the local computer is selected
  And the results appear newest first

Scenario: Partial remote failures remain visible with successful results
  Given an operator searches computers A and B and one remote search fails
  When the search results are returned
  Then the failed computer and reason are reported
  And successful remote results are still rendered
  And if no computer succeeds, the empty-result message names all requested computers
```

<!-- planned:history-search-all-computers -->

#### UC-CCHF-9: An operator searches history on every computer in the fleet

```
Scenario: Search every computer without naming them
  Given the fleet roster lists computers A and B online beside this computer
  When an operator runs `telec history search <terms> --computer all`
  Then this computer, A and B are searched in parallel
  And matching conversations from all three appear in one result list, newest first
  And each result identifies its computer

Scenario: A computer the roster lists offline is named, not searched
  Given the fleet roster lists computer C offline
  When an operator runs `telec history search <terms> --computer all`
  Then C is reported as not searched because it is offline
  And no request is sent to C
  And the results of every searched computer are still rendered

Scenario: all stands alone
  When an operator runs `telec history search <terms> --computer all --computer A`
  Then the search is refused before any computer is searched
  And the refusal states that `all` cannot be combined with named computers

Scenario: The roster cannot be read
  Given this computer's daemon does not accept the request for the fleet roster
  When an operator runs `telec history search <terms> --computer all`
  Then this computer's results are rendered
  And the failure to reach the rest of the fleet is reported with the daemon's cause
  And the command exits non-zero
```

<!-- /planned:history-search-all-computers -->

#### UC-CCHF-5: Cross-computer search travels the daemon relay

#### UC-CCHF-7: A caller retrieves a conversation from a selected computer

```
Scenario: Read a conversation from a peer
  Given a caller can access a session on computer "peer"
  When an operator runs `telec history show <session-id> --computer <peer>`, with or without `--raw`
  Then the CLI renders the peer's answer as it renders a local one

Scenario: The peer has no conversation within the caller's scope
  Given the peer holds no conversation for that identifier within the caller's scope
  When the operator requests that session's history from the peer
  Then the CLI reports "No transcript found for session '<session-id>'" and exits non-zero

Scenario: The peer cannot answer the request
  Given the relay cannot complete the request (timeout, unreachable peer, peer error, or a peer that does not carry the detail command)
  When the operator requests that session's history from the peer
  Then the CLI reports "Failed to fetch session '<session-id>' from <peer>: <reason>" and exits non-zero
```

## Known caveats

<!-- planned-change:history-search-all-computers -->

- When `--computer` is set, only the named computers are searched: local
  mirrors on the dispatching host are included only when its own name is among
  them. There is no "include local" toggle; an operator wanting the local
  results beside remote ones names the local computer too, or runs the command
  twice (once with `--computer`, once without).

<!-- change:history-search-all-computers -->

- When `--computer` is set, only the named computers are searched: local
  mirrors on the dispatching host are included only when its own name, or
  `all`, is among them. There is no "include local" toggle; an operator
  wanting the local results beside remote ones names the local computer too,
  or names `all`.
- A search without `--computer` reads only this computer. The roster keeps a
  computer it discovered listed online until this computer's daemon restarts,
  even after that computer leaves the fleet, so a search of every computer
  waits out the request's time limit for one that has left and reports it as
  failed.

<!-- /planned-change:history-search-all-computers -->

- A remote request waits a bounded time for the peer's relay answer. A slow
  or paused peer produces a timeout failure without retry.
- The remote search payload omits some local-only columns
  (`conversation_text`, `human_email`, `visibility`); rows are
  reconstructed from the wire payload for sort/render only.
- For show with `--raw`, the peer's transcript answer is printed whole. No
  cut is applied on either side.
