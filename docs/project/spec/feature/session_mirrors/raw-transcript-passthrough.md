---
id: 'project/spec/feature/session_mirrors/raw-transcript-passthrough'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Direct passthrough to the original agent transcript file when callers want raw transcript bytes rather than the mirror''s normalized conversation text. Exposed via `telec history show --raw` and via the session_mirrors service''s raw-transcript capability.'
---

# Raw Transcript Passthrough — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

Some debugging and forensic workflows need the original agent transcript
verbatim — tool calls, thinking blocks, system reminders — rather than
the mirror's text-only normalized conversation. Two paths expose this:

1. `telec history show --raw <session-id>` — the CLI first looks up the
   mirror; if found, it reads the `transcript_path` recorded in the
   mirror's metadata and streams the file directly. If no mirror is
   found, the CLI falls back to its on-disk transcript discovery (prefix
   match over the per-agent session roots) and renders that file via the
   structured parser.
2. The session_mirrors service's raw-transcript capability — given a
   session id, the capability looks up the mirror, resolves
   `metadata.transcript_path`, expands `~`, and returns the file content
   as UTF-8 text.

Both paths honor a `--tail <N>` character cut on the response so callers
can peek at the end of a long transcript without streaming the whole file.

## Canonical fields

### Use cases

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

#### Raw-transcript capability wire format

```
Given a mirror exists for session_id S with metadata.transcript_path = P that exists on disk
When a caller invokes the raw-transcript capability for S
Then the response is the UTF-8 content of P returned as plain text

Given the mirror is missing
Then the capability reports "Mirror not found"

Given the mirror exists but metadata.transcript_path is missing or not a string
Then the capability reports "Transcript path missing"

Given the mirror exists with a transcript_path but the file does not exist
Then the capability reports "Transcript file not found"
```

#### Remote --raw passthrough

```
Given an operator runs `telec history show S --raw --computer <name>`
When the CLI resolves the remote computer
Then the CLI invokes the remote session_mirrors service's raw-transcript capability for S
And applies --tail character trimming to the response body
And prints the trimmed content
```

## Known caveats

- The raw-transcript capability returns the full file in a single
  response — there is no chunked or range support. Long transcripts may
  produce large responses.
- The CLI fallback discovery uses a permissive match (extracted session
  id startswith OR stem substring contains). Multiple transcripts may
  match a short id; only the first hit by directory iteration is
  returned.
- The raw-transcript capability does not apply tail trimming —
  tail-trimming is a client (CLI) concern when fetching remotely.
- `metadata.transcript_path` is recorded at mirror creation time and is
  not refreshed when the agent runtime relocates or prunes the file. A
  "Transcript file not found" outcome is the normal result once the
  agent runtime has pruned its own transcript while the mirror persists.
