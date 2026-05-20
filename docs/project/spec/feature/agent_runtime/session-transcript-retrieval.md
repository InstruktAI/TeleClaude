---
id: 'project/spec/feature/agent_runtime/session-transcript-retrieval'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'On-demand read of a session''s native agent transcript via GET /sessions/{id}/messages, with chain-aware projection, since/tools/thinking filtering, and a tmux-tail fallback.'
---

# Session Transcript Retrieval — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The read-side observation surface for a single running session. A caller asks the daemon "what has this agent said?" and the daemon answers by parsing the agent's own native transcript files (Claude `.jsonl`, Codex rollouts, Gemini chat history) and projecting them into a structured `SessionMessagesDTO`.

The retrieval is **chain-aware**: a session that has been revived multiple times carries a `transcript_files` list of every prior native transcript plus the currently-active `native_log_file`. The projector reads the whole chain so a revived session presents one continuous message history.

This is the _on-demand_ live read. It is NOT the background polling-and-delivery loop that powers listeners (its own snippet) and it is NOT the eternal text-extract layer stored by `session_mirrors` (a different bounded context, populated only at session end).

## Canonical fields

### Behavioral contract

#### Happy path

```
Given an authenticated caller GETs /sessions/{session_id}/messages
And the session exists in the agent_runtime ledger
And at least one transcript file in (transcript_files chain ∪ {native_log_file}) is present on disk
When get_session_messages handles the request
Then _build_message_chain assembles the chain from session.transcript_files (JSON list) plus session.native_log_file if not already present
And _project_session_messages calls conversation_projector_module.project_conversation_chain with:
  - the chain (in order),
  - the parser agent resolved from session.active_agent via agents_module.resolve_parser_agent,
  - a VisibilityPolicy(include_tools, include_tool_results, include_thinking) honoring the query flags,
  - the since cutoff
And each projected block is serialized via output_serializers.to_structured_message into a MessageDTO carrying {role, type, text, timestamp, entry_index, file_index}
And the daemon returns SessionMessagesDTO including session_id, active_agent, last_activity, last_input_at, last_agent_stop_at, agent_status (computed by compute_agent_status), and the messages list
```

#### Filtering knobs

```
Given the caller sets query params on the request
When _parse_session_messages_query builds the SessionMessagesQuery
Then since: an ISO 8601 UTC timestamp; the projector drops entries strictly before it
And include_tools: when False, tool_use / tool_result blocks are excluded from the projection AND from MessageDTO output
And include_thinking: when False, thinking / reasoning blocks are excluded
And tail_chars: bounds the FALLBACK tmux/session tail char budget only (default 10000); has no effect on the structured-transcript path
And entry_index + file_index on each MessageDTO identify the source position (which file in the chain, which entry within it) so downstream callers can dedupe across reads
```

#### Transcript files missing or yield nothing

```
Given the chain is empty OR every file in the chain is missing on disk OR parsing produces zero structured blocks
When get_session_messages discovers the empty result
Then it dispatches GetSessionDataCommand(session_id, since_timestamp=since, tail_chars=tail_chars when positive, otherwise 10000) through CommandService.get_session_data
And if the resulting payload["messages"] is a non-empty string, packages it as a SINGLE MessageDTO(role="assistant", type="text", text=<that string>, timestamp=None, entry_index=0, file_index=0)
And otherwise returns an empty messages list
And status/timestamp/agent_status fields are still populated from session-ledger metadata
```

The fallback is the "tmux tail" path — for sessions whose transcript has not yet appeared (agent just started, native file not flushed) or has been removed (e.g., the agent CLI rotated logs), the daemon scrapes the live tmux pane buffer through `get_session_data` and returns the raw assistant-side text as one block.

#### Role inference

```
Given a transcript entry carries no explicit role on its envelope
When the conversation projector decides the role for the projected block
Then the per-agent parser resolved by agents_module.resolve_parser_agent supplies the default
  (Claude transcripts: explicit role on each entry; Codex / Gemini: parser-supplied defaults)
And MessageDTO.role reflects the projected block's role verbatim
```

Within `sessions_actions_routes.py`, `_infer_role_from_message` exists as a slash-command-prefix heuristic for run-session dispatch — it is NOT used to label transcript reads. Transcript role inference lives inside `output_projection.conversation_projector` and the per-agent parsers.

#### Session not found / access denied

```
Given the caller GETs /sessions/{session_id}/messages and the session does not exist
When db.get_session returns None
Then the daemon raises HTTPException 404 ("Session not found")
And no transcript I/O is attempted

Given the caller lacks access (check_session_access fails)
When the dependency check raises
Then the daemon returns the access-control error from check_session_access (typically 403)
```

### Implementation pointers (v1)

- `teleclaude/api/sessions_actions_routes.py:541` — `get_session_messages` (FastAPI handler for `GET /sessions/{id}/messages`)
- `teleclaude/api/sessions_actions_routes.py:124` — `_parse_session_messages_query` (since / include_tools / include_thinking / tail_chars)
- `teleclaude/api/sessions_actions_routes.py:194` — `_build_message_chain` (parse `session.transcript_files` JSON list, append `native_log_file`)
- `teleclaude/api/sessions_actions_routes.py:209` — `_project_session_messages` (drives `conversation_projector_module.project_conversation_chain` + `output_serializers.to_structured_message`)
- `teleclaude/api/sessions_actions_routes.py:259` — `_infer_role_from_message` (slash-command heuristic for dispatch, NOT for transcript projection; included for completeness)
- `teleclaude/output_projection/conversation_projector.py` — `project_conversation_chain` (the chain-aware projector)
- `teleclaude/output_projection/serializers.py:47` — `to_structured_message` (ProjectedBlock → MessageDTO; copies role through)
- `teleclaude/api/transcript_converter.py` — SSE-side converters (`convert_text_block`, `convert_thinking_block`, `convert_tool_use_block`, `convert_tool_result_block`, `convert_projected_block`) that share the underlying projected-block model
- `teleclaude/core/agents.py` — `resolve_parser_agent` (per-active-agent parser selection)
- `teleclaude/core/session_status.py` — `compute_agent_status` (idle / busy / stopped derivation used in the DTO)
- `teleclaude/types/commands.py` — `GetSessionDataCommand` (fallback tail dispatch)
- CLI verb: `telec sessions tail <session_id>` with `--since <ts>`, `--tools`, `--thinking` (`--session` is a routing flag for cross-computer fetches)

### Cross-context references

- **session_mirrors** — Explicitly NOT what this endpoint returns. The mirror layer is an eternal text extract published only at session end and lives in its own bounded context; this endpoint always reads the live native transcripts.
- **identity** — `clearance_sessions_tail` gates access; `check_session_access` enforces per-session ACLs.
- **config** — Transcript path resolution depends on per-agent locations (Claude CLI projects dir, Codex transcripts dir, Gemini chat history dir) defined under `teleclaude/core/agents/*` and surfaced through `config`.
- **session_ledger** — `session.transcript_files`, `session.native_log_file`, `session.active_agent`, `session.last_activity`, `session.last_message_sent_at`, `session.last_agent_stop_at` all come from session-ledger storage; this endpoint is read-only against the ledger.

## Known caveats

- **Chain is authoritative; missing files are silently skipped.** `_build_message_chain` returns paths even when they no longer exist; `project_conversation_chain` opens each one and ignores entries it cannot read. There is no error surfaced when a prior transcript has been pruned or moved — the chain just "starts later".
- **Fallback collapses many lines into one MessageDTO.** When the structured path yields no entries, the tmux-tail text is returned as a single `assistant` text block with `entry_index=0, file_index=0`. Callers expecting one DTO per logical message must detect this case (e.g., by the synthetic `timestamp=None`).
- **`since` semantics are projector-defined.** The projector compares against entry timestamps when they are present; entries without timestamps cannot be reliably filtered and may pass through.
- **`include_tools` is one knob for tool_use AND tool_result.** The endpoint sets both `include_tools` and `include_tool_results` on the `VisibilityPolicy` from the single query flag — a caller cannot ask for tool_use only.
- **`tail_chars` only affects the fallback path.** It is silently ignored when the structured projection succeeds. Positive values are honored as supplied; zero or negative values fall back to 10000 inside `get_session_messages` (`tail_chars if tail_chars > 0 else 10000`).
- **Revivals widen the chain monotonically.** Each `agent_restart` / revive that begins a new native session appends to `session.transcript_files`; old files remain referenced. Disk pressure scales with revive count for long-lived sessions.
- **No streaming.** This endpoint returns a single snapshot. The live streaming surface is the SSE / listener path described elsewhere.
- **Role inference is parser-supplied, not endpoint-supplied.** Don't expect `get_session_messages` to second-guess `MessageDTO.role` — it is exactly what the per-agent parser produced. The slash-command `_infer_role_from_message` in the same module is an unrelated dispatch-side helper.
- **Agent status is computed at call time.** `compute_agent_status` derives `agent_status` from `last_activity` / `last_message_sent_at` / `last_agent_stop_at` on every call; clients comparing successive responses see the value drift as time passes even without new messages.
