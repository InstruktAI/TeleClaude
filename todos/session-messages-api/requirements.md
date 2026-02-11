# Requirements: Session Messages API

## Goal

Expose structured session messages via an API endpoint backed by native session transcript files. The web frontend (and any future consumer) can inflate a full conversation thread by calling this endpoint, regardless of whether the session's transcript spans multiple files due to compaction or resume.

## Problem Statement

Today `get_session_data` reads a single `native_log_file` from the DB and returns markdown. Two problems:

1. **Single file** — the DB field `native_log_file` is a scalar string that gets replaced when a new transcript path arrives via hooks. If a session rotates files (e.g. Claude Code `--resume` within the same tmux session), the previous file path is lost.
2. **Markdown output** — the only way to read session data is `parse_session_transcript()` which returns rendered markdown. The web frontend needs structured message objects to render its own UI.

## Scope

### In scope

1. **Transcript file chain** — accumulate native transcript paths per session instead of replacing. When `_update_session_native_fields` detects a new `native_log_file` that differs from the stored one, append to the chain rather than overwrite.
2. **Messages API endpoint** — `GET /sessions/{session_id}/messages` returning structured JSON with role, text, timestamp, and entry metadata for each message.
3. **Multi-file stitching** — the endpoint reads all files in the chain sequentially, yielding messages in chronological order.
4. **Compaction markers** — `system` entries in Claude Code transcripts that mark context compaction are exposed as first-class `system` role messages with `type: "compaction"`.
5. **Incremental fetch** — `since` query parameter (ISO 8601 timestamp) to fetch only messages after a given point.
6. **Multi-agent support** — works for Claude, Codex, and Gemini session files using existing `_iter_*_entries()` iterators.

### Out of scope

- SSE streaming (that's web-interface-1).
- Authentication/authorization on the endpoint (that's person-identity-auth).
- Changing TUI behavior around compaction (TUI wraps tmux, pass-through).
- Message editing or mutation.
- Pagination beyond timestamp-based `since` (can be added later if needed).

## Functional Requirements

### FR1: Transcript file chain storage

- New DB field or structure to hold an ordered list of transcript file paths per session.
- When a hook arrives with a `native_log_file` different from the current one, the old path is preserved and the new path is appended.
- `native_log_file` continues to point to the latest file for backward compatibility with existing consumers (`get_session_data`, checkpoint logic, etc.).

### FR2: Messages endpoint

- `GET /sessions/{session_id}/messages`
- Query parameters:
  - `since` (optional) — ISO 8601 UTC timestamp. Only messages after this time are returned.
  - `include_tools` (optional, default false) — whether to include tool use/result entries.
  - `include_thinking` (optional, default false) — whether to include thinking/reasoning blocks.
- Response body:
  ```json
  {
    "session_id": "...",
    "agent": "claude",
    "messages": [
      {
        "role": "user" | "assistant" | "system",
        "type": "text" | "compaction" | "tool_use" | "tool_result" | "thinking",
        "text": "...",
        "timestamp": "2026-02-11T10:30:00Z",
        "entry_index": 7,
        "file_index": 0
      }
    ]
  }
  ```
- Messages are ordered chronologically across all files in the chain.

### FR3: Compaction event representation

- Claude Code `system` entries with `parentUuid` that appear after the initial session start are classified as compaction events.
- Returned as `{"role": "system", "type": "compaction", "text": "Context compacted", ...}`.
- The web frontend renders these as visual separators, not screen clears.

### FR4: Multi-file stitching

- When a session has multiple transcript files, the endpoint reads them in chronological order (oldest first).
- Messages from file N appear before messages from file N+1.
- Each message includes `file_index` to indicate which file it came from.

## Success Criteria

- [ ] Hook receiver preserves old transcript paths when a new one arrives for the same session.
- [ ] `GET /sessions/{id}/messages` returns structured JSON with all messages from the session.
- [ ] Multi-file sessions return messages stitched in chronological order.
- [ ] Compaction events appear as system messages in the response.
- [ ] `since` parameter correctly filters to only newer messages.
- [ ] Works for Claude, Codex, and Gemini session files.
- [ ] Existing `get_session_data` and checkpoint logic continue to work unchanged.

## Constraints

- Must not break existing `native_log_file` consumers — backward compatible.
- Must use existing `_iter_*_entries()` infrastructure from `transcript.py`, not duplicate parsing logic.
- Response size: no hard limit for now, but the endpoint should be efficient for large session files (stream/iterate, don't load all into memory at once).

## Risks

- Claude Code file rotation has not been observed in production yet (all `native_log_file_before` transitions are from empty). The chain storage is forward-looking. If the assumption about how `--resume` works is wrong, the chain logic is harmless (single-element chain).
- Large session files (6000+ JSONL lines observed) could make full message extraction slow. Mitigation: the `since` parameter avoids full re-parsing on incremental fetches.

## Dependencies

- None. This is pure daemon-side plumbing on existing infrastructure.
- This todo is a **prerequisite for** `web-interface-1` (SSE plumbing needs structured message source).
