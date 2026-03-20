# mirror-timestamp-fix — Input

Mirror conversation_text drops per-message timestamps. _render_conversation in teleclaude/mirrors/generator.py renders StructuredMessage as plain 'Role: text' pairs, discarding the .timestamp field. MirrorRecord only stores timestamp_start/timestamp_end at record level. Impossible to do time-windowed extraction from mirror data. session-memory-extraction depends on this fix. _render_conversation must preserve per-message timestamps so downstream consumers can filter by time within already-cleaned mirror output.
