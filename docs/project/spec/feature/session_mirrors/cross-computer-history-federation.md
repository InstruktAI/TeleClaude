---
id: 'project/spec/feature/session_mirrors/cross-computer-history-federation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
status: 'actual'
applies_to: 'v1'
description: 'Fan-out of `telec history search` and `telec history show` to one or more remote computers via the local daemon''s computer cache and each remote''s HTTP mirror API. Local mirrors are NOT searched when --computer is used.'
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
single-valued for show). When any `--computer` is present, the local daemon's
UDS endpoint resolves each computer name to an HTTP base URL by looking it
up in the daemon's local computer cache, and the CLI calls each remote
`/api/mirrors/*` route directly.

For search, all remote calls run in parallel via `asyncio.gather`, errors are
surfaced per-host, and the merged result list is re-sorted by `sort_timestamp`
descending before rendering. For show, exactly one computer is allowed and
the request flow is one HTTP call (either `/api/mirrors/{id}` or
`/api/mirrors/{id}/transcript` depending on `--raw`).

## Canonical fields

### Behavioral contract

#### Search fan-out across multiple computers

```
Given an operator runs `telec history search <terms> --computer A --computer B`
When the CLI begins remote dispatch
Then the local daemon's UDS endpoint /computers is fetched once via httpx
And each named computer is resolved to "http://<host>:<API_TCP_PORT>"
And asyncio.gather issues GET /api/mirrors/search to every resolved base URL in parallel
And local mirrors are NOT included in the merged result
And the merged rows are sorted by sort_timestamp DESC and rendered with a "computer" column
```

#### Per-host error reporting

```
Given one remote search raises an exception (timeout, connection refused, HTTP error)
When the gathered results are processed
Then a line "[<computer>] Remote search failed: <exception>" is printed to stdout
And successful remote results are still rendered
And the empty-result message lists all requested computers if nothing succeeded
```

#### Computer name not in local daemon cache

```
Given an operator passes --computer X
And the local daemon's /computers payload does not include X
When the CLI resolves the remote URL
Then an error "Computer 'X' not found in local daemon cache" is queued
And the failed host is reported with that error before / after the merged results
```

#### Local-daemon discovery failure

```
Given the local daemon UDS is unreachable when the CLI calls /computers
When the CLI resolves remote URLs
Then every requested computer gets the same error
  "Failed to resolve remote computers via local daemon: <exception>"
And no HTTP calls are made to any remote computer
```

#### Show enforces single computer

```
Given an operator runs `telec history show S --computer A --computer B`
When the CLI begins remote dispatch
Then it prints "history show accepts exactly one --computer value"
And exits with status code 1 without issuing any HTTP call
```

#### Show passes through to remote API

```
Given `telec history show S --computer A` and A is resolved
When the CLI dispatches the show
Then the CLI issues GET /api/mirrors/S (or /api/mirrors/S/transcript when --raw)
And on success the JSON payload is rendered locally by reconstructing a MirrorRecord
And on transport failure "Failed to fetch session 'S' from A: <exception>" is printed and exit 1
```

### V1 implementation pointers

- `teleclaude/history/search.py:display_combined_history` — local-vs-remote branch in `if computers:`.
- `teleclaude/history/search.py:_resolve_remote_computer_urls` — UDS lookup against `/computers` and per-host URL composition.
- `teleclaude/history/search.py:_fetch_local_daemon_computers` — UDS transport via `httpx.HTTPTransport(uds=API_SOCKET_PATH)`.
- `teleclaude/history/search.py:_remote_search` / `_run_remote_searches` — parallel `httpx.AsyncClient` GETs aggregated by `asyncio.gather(..., return_exceptions=True)`.
- `teleclaude/history/search.py:show_transcript` — show-side branch including the single-computer enforcement and the `--raw` route selection.
- `teleclaude/history/search.py:API_TCP_PORT` / `BASE_URL` — port resolved from `API_TCP_PORT` env var (default 8420).
- `teleclaude/cli/telec/handlers/history.py:_handle_history_search` / `_handle_history_show` — `--computer` repeated-value collection.
- `teleclaude/mirrors/api_routes.py:search_mirror_routes` / `get_mirror_route` / `get_mirror_transcript_route` — endpoints called by the remote dispatch.

## Known caveats

- When `--computer` is set, local mirrors on the dispatching host are
  intentionally NOT mixed into the result. There is no "include local"
  toggle; an operator wanting the local results too must run the command
  twice (once with `--computer`, once without).
- Role filtering does NOT propagate to remote computers. Each remote
  `/api/mirrors/*` call bypasses the role filter (see
  `role-scoped-history-access` known caveats). A non-admin operator can
  enumerate every mirror on a reachable remote.
- The remote HTTP timeout is hard-coded to 5 seconds per call. Slow or
  paused remotes produce a transport error without retry.
- The remote search rebuilds rows from the wire payload; the local
  `sort_timestamp` field is read but row metadata such as
  `conversation_text`, `human_email`, and `visibility` are not requested
  (the response schema omits them).
- For show with `--raw`, the remote transcript file is returned in full and
  `--tail` is applied client-side. There is no server-side trimming.
