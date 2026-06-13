---
description: "On-demand read of a session's native agent transcript, with chain-aware projection, since/tools/thinking filtering, and a pane-tail fallback."
visibility: 'public'
---

# Session Transcript Retrieval — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The read-side observation surface for a single running session. A caller asks the agent_runtime service "what has this agent said?" and the service answers by parsing the agent's own native transcript files (Claude transcripts, Codex rollouts, Gemini chat history) and projecting them into a structured messages payload.

The retrieval is **chain-aware**: a session that has been revived multiple times carries a transcript-files list of every prior native transcript plus the currently-active native transcript file. The projector reads the whole chain so a revived session presents one continuous message history.

This is the _on-demand_ live read. It is NOT the background polling-and-delivery loop that powers listeners (its own snippet) and it is NOT the eternal text-extract layer stored by `session_mirrors` (a different bounded context, populated only at session end).

## Canonical fields

### Use cases

#### Happy path

```
Given an authenticated caller asks the agent_runtime service for the session's transcript
And the session exists in the agent_runtime ledger
And at least one transcript file in (transcript-files chain ∪ {native transcript file}) is present on disk
When the transcript-retrieval flow runs
Then the message-chain builder assembles the chain from the session's transcript-files list plus the session's native transcript file if not already present
And the projection step calls the conversation projector with:
  - the chain (in order)
  - the parser agent resolved from the session's active agent
  - a visibility policy (include tools, include tool results, include thinking) honoring the query flags
  - the since cutoff
And each projected block is serialized into a message entry carrying {role, type, text, timestamp, entry index, file index}
And the service returns the session messages payload including session id, active agent, last activity, last input at, last agent stop at, agent status (computed by the status helper), and the messages list
```

#### Filtering knobs

```
Given the caller sets query parameters on the request
When the query is parsed
Then `since`: an ISO 8601 UTC timestamp; the projector drops entries strictly before it
And `include_tools`: when false, tool-use / tool-result blocks are excluded from the projection AND from the output
And `include_thinking`: when false, thinking / reasoning blocks are excluded
And `tail_chars`: bounds the FALLBACK pane/session output character budget only (default 10000); has no effect on the structured-transcript path or the pane-capture line window
And entry index + file index on each message entry identify the source position (which file in the chain, which entry within it) so downstream callers can dedupe across reads
```

#### Transcript files missing or yield nothing

```
Given the chain is empty OR every file in the chain is missing on disk OR parsing produces zero structured blocks
When the transcript-retrieval flow discovers the empty result
Then it dispatches a get-session-data command (session id, since timestamp = since, tail chars = supplied positive value, otherwise default 10000) through the command service
And if the resulting payload's messages field is a non-empty string, packages it as a SINGLE message entry (role="assistant", type="text", text=<that string>, timestamp=None, entry index=0, file index=0)
And otherwise returns an empty messages list
And status/timestamp/agent-status fields are still populated from session-ledger metadata
```

The fallback is the "pane tail" path — for sessions whose transcript has not yet appeared (agent just started, native file not flushed) or has been removed (e.g., the agent CLI rotated logs), the service scrapes a bounded live host-pane window through the get-session-data command and returns the raw assistant-side text as one block.

#### UC-STR1: Terminal session agent status

```
Given the session ledger row is in a terminal lifecycle state (`closing` or `closed`)
Or the row carries a `closed_at` marker
When the transcript-retrieval flow computes the response's `agent_status`
Then the terminal lifecycle marker is authoritative over activity timestamps
And the response reports `agent_status="idle"` even when `last_agent_stop_at` is missing
And the message projection still returns any transcript or fallback content available for that session
```

#### Role inference

```
Given a transcript entry carries no explicit role on its envelope
When the conversation projector decides the role for the projected block
Then the per-agent parser resolved from the session's active agent supplies the default
  (Claude transcripts: explicit role on each entry; Codex / Gemini: parser-supplied defaults)
And the resulting message entry's role reflects the projected block's role verbatim
```

A slash-command-prefix heuristic exists adjacent to this flow for run-session dispatch — it is NOT used to label transcript reads. Transcript role inference lives inside the conversation projector and the per-agent parsers.

#### Session not found / access denied

```
Given the caller asks for the transcript of a session that does not exist
When the storage lookup returns nothing
Then the service refuses with "Session not found"
And no transcript I/O is attempted

Given the caller lacks access (the session-access check fails)
When the access check raises
Then the service returns the access-control error from the access check
```

### Cross-context references

- **session_mirrors** — explicitly NOT what this entry returns. The mirror layer is an eternal text extract published only at session end and lives in its own bounded context; this entry always reads the live native transcripts.
- **identity** — the transcript-read clearance gates access; the per-session access check enforces per-session ACLs.
- **config** — transcript path resolution depends on per-agent locations (Claude CLI projects directory, Codex transcripts directory, Gemini chat history directory) surfaced through configuration.
- **session_ledger** — the session's transcript files, native transcript file, active agent, last activity, last message sent at, and last agent stop at all come from session-ledger storage; this entry is read-only against the ledger.

## Known caveats

- **Chain is authoritative; missing files are silently skipped.** The chain builder returns paths even when they no longer exist; the projector opens each one and ignores entries it cannot read. There is no error surfaced when a prior transcript has been pruned or moved — the chain just "starts later".
- **Fallback collapses many lines into one message entry.** When the structured path yields no entries, the pane-tail text is returned as a single `assistant` text block with entry index = 0, file index = 0. Callers expecting one entry per logical message must detect this case (e.g., by the synthetic `timestamp=None`).
- **`since` semantics are projector-defined.** The projector compares against entry timestamps when they are present; entries without timestamps cannot be reliably filtered and may pass through.
- **`include_tools` is one knob for tool_use AND tool_result.** The entry sets both include-tools and include-tool-results on the visibility policy from the single query flag — a caller cannot ask for tool_use only.
- **`tail_chars` only affects fallback output truncation.** It is silently ignored when the structured projection succeeds. Positive values are honored as supplied; zero or negative values fall back to 10000. The fallback pane capture itself uses a small fixed line window before this character truncation is applied.
- **Revivals widen the chain monotonically.** Each agent restart / revive that begins a new native session appends to the session's transcript files; old files remain referenced. Disk pressure scales with revive count for long-lived sessions.
- **No streaming.** This entry returns a single snapshot. The live streaming surface is the SSE / listener path described elsewhere.
- **Role inference is parser-supplied, not entry-supplied.** Don't expect the transcript-retrieval flow to second-guess message roles — they are exactly what the per-agent parser produced. The slash-command role inference adjacent to this flow is an unrelated dispatch-side helper.
- **Agent status is computed at call time.** The status helper derives agent status from terminal lifecycle markers (`closing`, `closed`, `closed_at`) first, then from last activity / last message sent at / last agent stop at; clients comparing successive responses see the value drift as session metadata changes even without new messages.
