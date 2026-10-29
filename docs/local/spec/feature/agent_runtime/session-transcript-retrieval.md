---
description: "On-demand read of a session's native agent transcript, with chain-aware projection, since/tools/thinking filtering, and a pane-tail fallback."
visibility: 'public'
---

# Session Transcript Retrieval — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

The read-side observation surface for a single running session. A caller asks the agent_runtime service "what has this agent said?" and the service answers by parsing the agent's own native transcript files (Claude transcripts, Codex rollouts, Gemini chat history) and projecting them into a structured messages payload.

The retrieval is **chain-aware**: a session that has been revived multiple times carries a transcript-files list of every prior native transcript plus the currently-active native transcript file. The projector reads the whole chain so a revived session presents one continuous message history.

This is the _on-demand_ live read. It is NOT the background polling-and-delivery loop that powers listeners (its own snippet) and it is NOT the eternal text-extract layer stored by `session_mirrors` (a different bounded context, populated only at session end).

## Canonical fields

### Use cases

#### UC-STR3: A caller can read a session's conversation

```gherkin
Scenario: Read an existing session transcript
  Given a person asks an agent authorized to inspect a session within their reach
  When the agent reads that session's transcript
  Then it receives one continuous conversation across the session's transcript chain

Scenario: Read available output when native transcript messages are absent
  Given a person asks an agent to read a live session whose transcript files are missing or contain no readable messages
  When the agent retrieves that conversation
  Then it returns any available live session output or an empty result
  And current session metadata remains available

Scenario: A missing session is distinct from an out-of-reach refusal
  Given no session carries the id the person named
  When the agent requests that transcript
  Then the person receives a not-found result distinct from an out-of-reach refusal
  And no transcript file is read
```

#### UC-STR4: A caller can focus a transcript on relevant messages

```gherkin
Given a person needs only recent or selected types of messages from a session
When their agent requests transcript filters
Then the returned transcript reflects the requested time and content selection
And its messages retain their source positions
And a fallback text bound applies only when structured transcript content is unavailable
```

#### UC-STR5: A caller can read available session conversation without transcript files

The fallback is the "pane tail" path — for sessions whose transcript has not yet appeared (agent just started, native file not flushed) or has been removed (e.g., the agent CLI rotated logs), the service scrapes a bounded live host-pane window through the get-session-data command and returns the raw assistant-side text as one block.

The response carries the session id, active agent, last activity, last input,
last agent stop, and computed agent status. Transcript filters select the time
cutoff and whether tool-use/results or reasoning messages are included; returned
messages retain their source positions. The fallback text bound applies only
when structured transcript content is unavailable.

#### UC-STR1: Terminal session agent status

#### Role inference

A slash-command-prefix heuristic exists adjacent to this flow for run-session dispatch — it is NOT used to label transcript reads. Transcript role inference lives inside the conversation projector and the per-agent parsers.

#### UC-STR6: Session not found

#### UC-STR2: An agent can inspect the live terminal independently of transcript progress

```gherkin
Given an authorized parent agent investigates its child session
And the child has an existing transcript with no new messages
When the parent requests the child's current terminal state
Then it receives the available live terminal contents distinctly identified as terminal observation rather than authored conversation
And transcript availability or lack of new messages does not hide that observation
And a child with no available terminal is reported as such without inventing terminal contents
And inspection writes no input and makes no permission decision for the child
```

### Explicit terminal query

`telec sessions tail <session-id> --pane` requests a terminal observation from
`GET /sessions/{session-id}/pane`. The query uses the existing
session-read clearance and access contract.

The response identifies the target, its runtime, the capture time, and terminal
availability. Available contents are terminal evidence, never transcript
messages or an authored assistant turn. A missing terminal is reported
unavailable; a capture failure is surfaced as a failure. An empty available
terminal is distinct from an unavailable terminal.

The query writes no session input and does not parse the transcript. The default
tail command and messages endpoint retain their transcript projection and
fallback behavior. Transcript filtering flags apply to the transcript query;
they are not accepted with explicit terminal mode.

<!-- planned:github-turn-mirror -->

### Completed turns read

A consumer in another context reads a session's completed turns in order,
from the turn after one it already holds. It is a module query on the
computer that hosts the session, with no API or command-line surface, under
the same per-session access contract.

- **Turn.** An exchange the agent answered: it opens at a native user entry
  carrying input of any origin (a person's message, a peer's or the
  platform's message, a dispatch loader, a notification or a reminder) and
  includes every further input entry that arrived before the agent's answer.
  Turns are found from the session's transcript chain itself, so a turn the
  runtime never projected while it was not running is still a turn. A turn
  carries the runtime-qualified native identity of the entry that opened it
  and its ordinal among the session's turns, counted from one, which the
  runtime records the first time the read finds the turn and never changes.
  Output generations and their delivery are unaffected by the read.
- **Completion time.** When the turn's last entry was written.
- **Input.** The turn's authored input parts in order, each with its
  authorship: a person, with the channel their words arrived through; a peer
  session, with its id and role; the platform; or runtime content.
- **Reply.** The agent's user-visible text for the turn, every text block in
  order, without tool activity or reasoning.
- **Completion.** A turn is completed once the session has a later turn, its
  latest agent stop is at or after the turn's last entry, or the session is
  closed. Only completed turns are returned.
  The read covers the session's whole transcript chain. A chain file that no
  longer exists contributes no turns and is logged; a file that exists but fails
  to read fails the read.

<!-- /planned:github-turn-mirror -->

### Cross-context references

- **session_mirrors** — explicitly NOT what this entry returns. The mirror layer is an eternal text extract published only at session end and lives in its own bounded context; this entry always reads the live native transcripts.
- **identity** — the transcript-read clearance gates access; the per-session access check enforces per-session ACLs.
- **config** — transcript path resolution depends on per-agent locations (Claude CLI projects directory, Codex transcripts directory, Gemini chat history directory) surfaced through configuration.
- **session_ledger** — the session's transcript files, native transcript file, active agent, last activity, last message sent at, and last agent stop at all come from session-ledger storage; this entry is read-only against the ledger.

## Known caveats

- **Chain is authoritative; missing files are silently skipped.** The chain builder returns paths even when they no longer exist; the projector opens each one and ignores entries it cannot read. There is no error surfaced when a prior transcript has been pruned or moved — the chain just "starts later".
- **Fallback collapses many lines into one message entry.** When the structured path yields no entries, the pane-tail text is returned as a single `assistant` text block with entry index = 0, file index = 0. Callers expecting one entry per logical message must detect this case (e.g., by the synthetic `timestamp=None`).
- **`since` semantics are projector-defined.** The projector compares against entry timestamps when they are present; entries without timestamps cannot be reliably filtered and may pass through.
- **`include_tools` is one knob for pre_tool_use AND tool_result.** The entry sets both include-tools and include-tool-results on the visibility policy from the single query flag — a caller cannot ask for pre_tool_use only.
- **`tail_chars` only affects fallback output truncation.** It is silently ignored when the structured projection succeeds. Positive values are honored as supplied; zero or negative values fall back to 10000. The fallback pane capture itself uses a small fixed line window before this character truncation is applied.
- **Revivals widen the chain monotonically.** Each agent restart / revive that begins a new native session appends to the session's transcript files; old files remain referenced. Disk pressure scales with revive count for long-lived sessions.
- **Role inference is parser-supplied, not entry-supplied.** Don't expect the transcript-retrieval flow to second-guess message roles — they are exactly what the per-agent parser produced. The slash-command role inference adjacent to this flow is an unrelated dispatch-side helper.
- **Agent status is computed at call time.** The status helper derives agent status from terminal lifecycle markers (`closing`, `closed`, `closed_at`) first, then from last activity / last message sent at / last agent stop at; clients comparing successive responses see the value drift as session metadata changes even without new messages.
