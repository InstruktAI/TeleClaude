---
id: 'project/spec/feature/session_mirrors/conversation-text-extraction'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
status: 'actual'
applies_to: 'v1'
description: 'Normalization rules that turn a structured agent transcript into the mirror''s flat conversation_text — user and assistant text only, system-reminders stripped, title derived from the first user message, timestamps anchored on the first and last surviving messages.'
---

# Conversation Text Extraction — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

A mirror's `conversation_text` is the searchable artifact at the core of
historical search. Producing it deterministically is the generator's job.
The generator reads the structured transcript (excluding tool blocks and
thinking), keeps only `text`-typed `user` and `assistant` messages, strips
embedded `<system-reminder>…</system-reminder>` blocks from user text,
discards messages that become empty after stripping, and renders the
remaining sequence as `[<timestamp>] <Role>: <text>` blocks joined by blank
lines (or `<Role>: <text>` when the message carries no timestamp).

Three derived fields come along with the text body:
- `title` — the first user message's stripped text, truncated to 120 characters with `...` when longer.
- `timestamp_start` — the first surviving message's timestamp.
- `timestamp_end` — the last surviving message's timestamp.

An extraction that produces zero normalized messages signals to the caller
to delete any existing mirror and (in the worker path) record a tombstone
instead of writing a row.

## Canonical fields

### Behavioral contract

#### Filter to text-only user/assistant messages

```
Given a structured transcript with mixed message types (text, tool_use, tool_result, thinking)
When the generator calls _normalize_conversation_messages(messages)
Then only messages with type == "text" AND role in {"user", "assistant"} survive
And tool blocks, thinking blocks, and tool_result blocks are excluded
```

#### Strip system-reminder blocks from user text

```
Given a user message text containing <system-reminder>...</system-reminder> (across newlines)
When _clean_user_text is applied
Then every <system-reminder>...</system-reminder> block is removed (re.DOTALL)
And the result is whitespace-stripped
Given the cleaned user text is empty
Then the message is dropped from the normalized list
```

#### Assistant text passes through trimmed

```
Given an assistant message text
When normalization runs
Then assistant text is .strip()'d but otherwise unchanged
And no system-reminder stripping is applied to assistant text
And an assistant message that strips to empty is dropped
```

#### Title derivation

```
Given normalized messages exist
When _title_from_messages runs
Then the title is the first user message's stripped text
And if the text is <= 120 chars it is used verbatim
And if longer, the first 117 chars (after right-strip) are used followed by "..."
Given no user message exists in the normalized list
Then the title is "" (empty string)
```

#### Rendered conversation_text format

```
Given a normalized message list
When _render_conversation runs
Then each message is rendered as
  "[<timestamp>] <Role>: <text>"  when timestamp is set
  OR "<Role>: <text>"             when timestamp is None
And messages are joined by a blank line (two newlines)
And role is title-cased (.capitalize()): User, Assistant
```

#### Empty extraction signals "no mirror"

```
Given _normalize_conversation_messages returns an empty list
When generate_mirror_sync runs
Then delete_mirror(session_id, source_identity, db) is invoked
And the function returns False
And no upsert occurs
```

#### Successful extraction upserts the mirror

```
Given normalized messages exist
When generate_mirror_sync runs
Then timestamp_start is the first surviving message's timestamp
And timestamp_end is the last surviving message's timestamp
And message_count equals len(normalized)
And the mirror is upserted with created_at preserved when an existing row was found
And updated_at is the current UTC ISO timestamp
And the function returns True
```

#### Async surface

```
Given a caller awaits generate_mirror(...)
When the call resolves
Then generate_mirror_sync ran inside asyncio.to_thread off the event loop
And the same keyword arguments are forwarded
```

### V1 implementation pointers

- `teleclaude/mirrors/generator.py:generate_mirror_sync` — sync entry; orchestrates extraction → upsert.
- `teleclaude/mirrors/generator.py:generate_mirror` — async wrapper via `asyncio.to_thread`.
- `teleclaude/mirrors/generator.py:_normalize_conversation_messages` — type/role filter and per-role text handling.
- `teleclaude/mirrors/generator.py:_clean_user_text` — system-reminder strip via `_SYSTEM_REMINDER_RE` (re.DOTALL).
- `teleclaude/mirrors/generator.py:_title_from_messages` — first user message, 120-char truncation.
- `teleclaude/mirrors/generator.py:_render_conversation` — `[<ts>] <Role>: <text>` lines joined by blank lines.
- `teleclaude/mirrors/generator.py:_TITLE_MAX_CHARS` — 120.
- `teleclaude/utils/transcript.py:extract_structured_messages` — upstream parser called with `include_tools=False, include_thinking=False`.

## Known caveats

- Stripping system-reminders happens on user text only. An assistant message
  that quotes a reminder verbatim retains the quote.
- Title is derived only from user messages; a session where the assistant
  spoke first (rare) yields title = "".
- Timestamp rendering uses the structured message timestamp as-is — no
  reformatting, no timezone conversion. Stored format is whatever the
  agent CLI's transcript provided.
- Message-count is the count of NORMALIZED messages (post-filter), not the
  count of raw structured blocks in the transcript.
- The renderer uses `.capitalize()` so any role string outside the
  {"user","assistant"} set would render with only its first letter
  capitalized. The pre-filter eliminates other roles so this is currently
  not observable.
