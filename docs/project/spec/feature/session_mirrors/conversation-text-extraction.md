---
id: 'project/spec/feature/session_mirrors/conversation-text-extraction'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Normalization rules that turn a structured agent transcript into the mirror''s flat conversation_text — user and assistant text only, system-reminders stripped, title derived from the first user message, timestamps anchored on the first and last surviving messages.'
---

# Conversation Text Extraction — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

A mirror's `conversation_text` is the searchable artifact at the core of
historical search. Producing it deterministically is the
session_mirrors service's job. The extractor reads the structured
transcript (excluding tool blocks and thinking), keeps only text-typed
user and assistant messages, strips embedded `<system-reminder>` blocks
from user text, discards messages that become empty after stripping, and
renders the remaining sequence as `[<timestamp>] <Role>: <text>` blocks
joined by blank lines (or `<Role>: <text>` when the message carries no
timestamp).

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
When the session_mirrors service normalizes the transcript
Then only messages of type "text" with role "user" or "assistant" survive
And tool blocks, thinking blocks, and tool_result blocks are excluded
```

#### Strip system-reminder blocks from user text

```
Given a user message text containing one or more <system-reminder>...</system-reminder> blocks (spanning newlines)
When the extractor cleans the user text
Then every <system-reminder> block is removed in full
And the remaining text is whitespace-stripped
Given the cleaned user text is empty
Then the message is dropped from the normalized list
```

#### Assistant text passes through trimmed

```
Given an assistant message text
When normalization runs
Then the assistant text is whitespace-trimmed but otherwise unchanged
And no system-reminder stripping is applied to assistant text
And an assistant message that trims to empty is dropped
```

#### Title derivation

```
Given a non-empty normalized message list
When the extractor derives the title
Then the title is the first user message's stripped text
And if the text is 120 characters or fewer it is used verbatim
And if longer, the first 117 characters (right-trimmed) are used followed by "..."
Given no user message exists in the normalized list
Then the title is the empty string
```

#### Rendered conversation_text format

```
Given a normalized message list
When the extractor renders the conversation text
Then each message is rendered as
  "[<timestamp>] <Role>: <text>"  when a timestamp is present
  OR "<Role>: <text>"             when no timestamp is present
And messages are joined by a blank line
And role is title-cased (User, Assistant)
```

#### Empty extraction signals "no mirror"

```
Given normalization yields an empty list
When the session_mirrors service runs mirror generation
Then any existing mirror for the session is deleted
And the generation call reports "no conversation extracted"
And no mirror row is written
```

#### Successful extraction upserts the mirror

```
Given normalization yields one or more messages
When the session_mirrors service runs mirror generation
Then timestamp_start is the first surviving message's timestamp
And timestamp_end is the last surviving message's timestamp
And message_count equals the number of normalized messages
And the mirror is upserted; on update the created_at is preserved
And updated_at is set to the current UTC ISO timestamp
And the generation call reports success
```

#### Async surface

```
Given a caller awaits the async mirror generation entry point
When the call resolves
Then the synchronous extraction and upsert ran off the caller's event loop
And the resolved outcome is identical to the synchronous variant
```

## Known caveats

- Stripping system-reminders happens on user text only. An assistant message
  that quotes a reminder verbatim retains the quote.
- Title is derived only from user messages; a session where the assistant
  spoke first (rare) yields an empty title.
- Timestamp rendering uses the structured message timestamp as-is — no
  reformatting, no timezone conversion. Stored format is whatever the
  agent runtime's transcript provided.
- Message-count is the count of normalized messages (post-filter), not the
  count of raw structured blocks in the transcript.
- The role renderer title-cases only the first letter. Any role string
  outside {user, assistant} would render with only its first letter
  capitalized; the pre-filter eliminates other roles so this is not
  currently observable.
