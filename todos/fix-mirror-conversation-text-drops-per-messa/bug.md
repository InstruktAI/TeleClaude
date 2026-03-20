# Bug: Mirror conversation_text drops per-message timestamps. \_render_conversation in teleclaude/mirrors/generator.py renders StructuredMessage as plain 'Role: text' pairs, discarding the .timestamp field. MirrorRecord only stores timestamp_start/timestamp_end at record level. Impossible to do time-windowed extraction from mirror data. session-memory-extraction depends on this fix. \_render_conversation must preserve per-message timestamps so downstream consumers can filter by time within already-cleaned mirror output.

## Symptom

Mirror conversation_text drops per-message timestamps. \_render_conversation in teleclaude/mirrors/generator.py renders StructuredMessage as plain 'Role: text' pairs, discarding the .timestamp field. MirrorRecord only stores timestamp_start/timestamp_end at record level. Impossible to do time-windowed extraction from mirror data. session-memory-extraction depends on this fix. \_render_conversation must preserve per-message timestamps so downstream consumers can filter by time within already-cleaned mirror output.

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-20

## Investigation

`_render_conversation` in `teleclaude/mirrors/generator.py` (line 47) builds each line as
`f"{message.role.capitalize()}: {message.text}"`. The `StructuredMessage.timestamp` field
(`str | None`) is never referenced, so every per-message timestamp is silently dropped.
`MirrorRecord` stores only `timestamp_start`/`timestamp_end` at the record level, making
time-windowed filtering within the conversation text impossible.

The existing test `test_generate_mirror_sync_upserts_normalized_conversation_and_preserves_created_at`
pinned the broken format without timestamps, confirming no prior contract existed for timestamp inclusion.

## Root Cause

`_render_conversation` renders `StructuredMessage` objects as plain `Role: text` pairs without
consuming the `.timestamp` field, discarding per-message temporal context.

## Fix Applied

Changed `_render_conversation` to prefix each line with `[{timestamp}]` when the field is
non-None, producing `[2025-01-01T10:00:00+00:00] User: text`. Messages with `timestamp=None`
render unchanged as `Role: text` for backward compatibility.

Added three targeted unit tests in `TestRenderConversation` covering: timestamp present,
timestamp absent (None), and mixed presence. Updated the existing integration test to
expect the new timestamped format.
