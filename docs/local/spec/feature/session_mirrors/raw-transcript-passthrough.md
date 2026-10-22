---
description: "Direct passthrough to the original agent transcript file when callers want raw transcript bytes rather than the mirror's normalized conversation text. Streamed whole, matched on an exact session id. Exposed via `telec history show --raw`."
visibility: 'public'
---

# Raw Transcript Passthrough — Spec

## Required reads

- @docs/local/spec/domain/session_mirrors.md

## What it is

`telec history show --raw <session-id>` returns the original agent
transcript verbatim — tool calls, thinking blocks, system reminders — rather
than the mirror's text-only normalized conversation. The session_mirrors
service's history detail capability answers for the caller the platform
verifies. It first looks up
the mirror; if found, it reads the `transcript_path` recorded in the mirror's
metadata and returns the file whole. If no mirror is found and the caller's
scope admits every mirror, it falls back to its on-disk transcript discovery —
an exact match on the extracted session id over the per-agent session roots —
and returns that file rendered by the structured parser. The CLI prints the
answer and reads no file itself.

The answer takes no character cut. A transcript is streamed whole and bounded
by the caller's own tooling.

## Canonical fields

### Use cases

#### UC-RTP1: An operator reads an agent's original transcript

```gherkin
Scenario: Read a mirrored transcript verbatim
  Given a mirror within the caller's history scope exists for session_id S with metadata.transcript_path = P
  When an operator runs `telec history show S --raw`
  Then the history detail capability returns P read as UTF-8
  And the CLI prints the file content whole, without the mirror header

Scenario: Read a matching transcript when no mirror exists
  Given no mirror exists for session_id S
  And the caller's history scope admits every mirror
  And a transcript file whose extracted session id equals S exists in one of the per-agent session roots
  When an operator runs `telec history show S --raw`
  Then the history detail capability invokes the structured parser on the transcript file
  And returns the parsed text honoring --thinking, with tool blocks excluded
  And the CLI prints that text

Scenario: Report when no transcript matches
  Given no mirror exists and no transcript's extracted session id equals S
  When an operator runs `telec history show S --raw`
  Then the CLI prints "No transcript found for session '<S>'" and exits non-zero
```

## Known caveats

- The history detail capability returns the full file in a single
  answer — there is no chunked or range support. Long transcripts may
  produce large answers.
- The fallback discovery matches an extracted session id exactly, so a
  request never resolves to a transcript the caller did not name.
- Neither the capability nor the CLI trims the answer; a caller that wants
  part of a transcript bounds it with its own tooling.
- `metadata.transcript_path` is recorded at mirror creation time and is
  not refreshed when the agent runtime relocates or prunes the file. A
  raw request reporting no transcript found is the normal result once the
  agent runtime has pruned its own transcript while the mirror persists.
