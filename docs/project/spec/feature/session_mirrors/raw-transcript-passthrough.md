---
id: 'project/spec/feature/session_mirrors/raw-transcript-passthrough'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
status: 'actual'
applies_to: 'v1'
description: 'Direct passthrough to the original agent transcript file when callers want raw transcript bytes rather than the mirror''s normalized conversation text. Exposed via `telec history show --raw` and `/api/mirrors/{session_id}/transcript`.'
---

# Raw Transcript Passthrough — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

Some debugging and forensic workflows need the original agent transcript
verbatim — tool calls, thinking blocks, system reminders — rather than the
mirror's text-only normalized conversation. Two paths expose this:

1. `telec history show --raw <session-id>` — the CLI first looks up the
   mirror; if found, it reads the `transcript_path` recorded in mirror
   metadata and streams the file directly. If no mirror is found, the CLI
   falls back to its on-disk transcript discovery (prefix match over the
   per-agent session roots) and renders that file via the structured parser.
2. `GET /api/mirrors/{session_id}/transcript` — the HTTP route looks up the
   mirror, resolves `metadata.transcript_path`, expands `~`, and returns the
   file content as `text/plain` UTF-8.

Both paths honor a `--tail <N>` character cut on the response so callers can
peek at the end of a long transcript without streaming the whole file.

## Canonical fields

### Behavioral contract

#### CLI --raw with mirror present

```
Given a mirror exists for session_id S with metadata.transcript_path = P
When an operator runs `telec history show S --raw`
Then the CLI reads P as UTF-8
And applies --tail <N> character trimming (0 = unlimited) to the file content
And prints the resulting text without the mirror header
```

#### CLI --raw with no mirror

```
Given no mirror exists for session_id S
And a transcript file matching S (by extracted session id prefix or stem substring) exists in one of the per-agent session roots
When an operator runs `telec history show S --raw`
Then the CLI invokes the structured parser on the transcript file
And renders the parsed text honoring --tail and --thinking
And tool blocks are excluded from the rendering
```

#### CLI --raw with no mirror and no transcript

```
Given no mirror exists and no transcript matches by prefix or stem
When an operator runs `telec history show S --raw`
Then the CLI prints "No transcript found for session '<S>'" and exits non-zero
```

#### HTTP transcript wire format

```
Given a mirror exists for session_id S with metadata.transcript_path = P that exists on disk
When a caller issues GET /api/mirrors/{S}/transcript
Then the response is a PlainTextResponse with the UTF-8 content of P

Given the mirror is missing
Then the route returns HTTP 404 with detail "Mirror not found"

Given the mirror exists but metadata.transcript_path is missing or not a string
Then the route returns HTTP 404 with detail "Transcript path missing"

Given the mirror exists with a transcript_path but the file does not exist
Then the route returns HTTP 404 with detail "Transcript file not found"
```

#### Remote --raw passthrough

```
Given an operator runs `telec history show S --raw --computer <name>`
When the CLI resolves the remote computer's API base URL
Then the CLI fetches GET /api/mirrors/{S}/transcript from that computer
And applies --tail character trimming to the response body
And prints the trimmed content
```

### V1 implementation pointers

- `teleclaude/mirrors/api_routes.py:get_mirror_transcript_route` — HTTP `/api/mirrors/{session_id}/transcript` handler with the three 404 branches.
- `teleclaude/history/search.py:show_transcript` — CLI raw branches: local mirror → file read, fallback discovery, remote dispatch.
- `teleclaude/history/search.py:_tail_text` — tail-character trimming shared by mirror and raw paths.
- `teleclaude/history/search.py:find_transcript` — prefix / substring discovery over per-agent session roots.
- `teleclaude/utils/transcript.py:parse_session_transcript` — structured parser used for the no-mirror fallback.
- `teleclaude/cli/telec/handlers/history.py:_handle_history_show` — `--raw` and `--tail` argument parsing.

## Known caveats

- The HTTP route returns the raw file as a single response — there is no
  chunked / range support. Long transcripts may produce large responses.
- The CLI fallback discovery uses a permissive match (extracted session id
  startswith OR stem substring contains). Multiple transcripts may match a
  short id; only the first hit by directory iteration is returned.
- The HTTP route does not apply tail trimming server-side — tailing is a
  client (CLI) concern when fetching remotely.
- `metadata.transcript_path` is recorded at mirror creation time and is not
  refreshed when the agent CLI relocates or prunes the file. A 404 with
  "Transcript file not found" is the normal outcome once the agent CLI has
  pruned its own transcript while the mirror persists.
