---
description: "Normalization rules that turn a structured agent transcript into the mirror's flat conversation_text and derived fields — user and assistant text only, injected machine-context (system-reminders, AGENTS.md, environment_context, command tags) stripped, classification, command, slug and title taken from the session record (first real user message as the title when no record exists), and timestamps anchored on the first and last surviving messages."
visibility: 'public'
---

# Conversation Text Extraction — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

A mirror's `conversation_text` is the searchable artifact at the core of
historical search. Producing it deterministically is the
session_mirrors service's job. The extractor reads the structured
transcript (excluding tool blocks and thinking), keeps only text-typed
user and assistant messages, and strips embedded machine-context from user
text — `<system-reminder>` blocks, the injected `# AGENTS.md instructions
for …` heading and its adjacent `<INSTRUCTIONS>…</INSTRUCTIONS>` body,
`<environment_context>` blocks, `<hook_context>` blocks, and the
`<command-message>` / `<command-name>` / `<command-args>` launch tags. A
user turn whose text is a serialized content list (`[{'text': …}]`, a
malformed transcript artifact) is first unwrapped back to its concatenated
text before stripping. The extractor discards messages that become empty
after stripping and renders the remaining sequence as
`[<timestamp>] <Role>: <text>` blocks joined by blank lines (or
`<Role>: <text>` when the message carries no timestamp).

What a session is — a dispatched worker, an orchestrator, a human
conversation — is a fact the agent_runtime bounded context records on the
session record when it launches the session, together with the launch
command and the session title. The extractor takes those facts from the
record (see `mirror-identity-enrichment`) and never infers them from the
transcript's text. A transcript that has no session record is not a
session the platform dispatched: it is classified as not a worker, carries
no command or slug, and takes its title from its first user message.

Derived fields that come along with the text body:

- `command` — the launch command recorded on the session record (e.g. `next-review-plan`), else null.
- `slug` — the launch command's argument recorded on the session record, else null.
- `is_worker` — true exactly when the session record's system role is worker; false for every other role and for a transcript with no record.
- `title` — the session record's title; for a transcript with no record, the first user message's stripped text truncated at the first newline and then to 120 characters with `...` when longer.
- `timestamp_start` — the first surviving message's timestamp.
- `timestamp_end` — the last surviving message's timestamp.

An extraction that produces zero normalized messages writes no row and, in the
worker path, records a tombstone. An existing mirror keeps its stored conversation
text; only a source with no mirror clears its row. An extraction that yields fewer
messages than the stored mirror's `message_count` is refused: the stored mirror is
kept unchanged, the refusal is logged with both counts, and the caller is reported
the same "no conversation extracted" outcome.

## Canonical fields

### Use cases

#### UC-CTE-1: Filter to text-only user/assistant messages

```
Given a structured transcript with mixed message types (text, pre_tool_use, tool_result, thinking)
When the session_mirrors service normalizes the transcript
Then only messages of type "text" with role "user" or "assistant" survive
And tool blocks, thinking blocks, and tool_result blocks are excluded
```

#### UC-CTE-2: Strip injected machine-context from user text

```
Given a user message text containing injected machine-context — one or more <system-reminder>...</system-reminder> blocks, a leading "# AGENTS.md instructions for ..." heading with its adjacent <INSTRUCTIONS>...</INSTRUCTIONS> body, an <environment_context>...</environment_context> block, a <hook_context>...</hook_context> block, or <command-message>/<command-name>/<command-args> launch tags (each may span newlines)
When the extractor cleans the user text
Then every such injected block is removed in full
And the remaining text is whitespace-stripped
Given a user message text that is a serialized content list of the form [{'text': ...}] (a malformed transcript artifact)
When the extractor cleans the user text
Then the list is unwrapped to its concatenated text values before injected blocks are stripped
Given the cleaned user text is empty
Then the message is dropped from the normalized list
```

#### UC-CTE-3: Assistant text passes through trimmed

```
Given an assistant message text
When normalization runs
Then the assistant text is whitespace-trimmed but otherwise unchanged
And no machine-context stripping is applied to assistant text
And an assistant message that trims to empty is dropped
```

#### UC-CTE-4: Classification, command and slug come from the session record

```
Given a transcript whose session record carries a system role, a launch command, and a title
When the extractor derives the mirror's classification
Then is_worker is true exactly when the recorded system role is worker
And command and slug are the launch command and argument the record carries
And an orchestrator, tasker or integrator session is recorded with its command and is_worker = false
And no user turn is scanned for a launch marker, a command tag, a loader line, or a leading slash

Given a transcript with no session record
When the extractor derives the mirror's classification
Then is_worker is false with command and slug null
```

#### UC-CTE-5: Title derivation

```
Given a transcript whose session record carries a title
When the extractor derives the title
Then the mirror title is the record's title, so a launched session keeps the title the platform gave it and stays searchable whatever role it carries

Given a transcript with no session record
When the extractor derives the title
Then the title is the first user message's stripped text, truncated at the first newline and then to 120 characters (right-trimmed) with "..." when longer
Given no user message exists in the normalized list
Then the title is the empty string
```

#### UC-CTE-6: Rendered conversation_text format

```
Given a normalized message list
When the extractor renders the conversation text
Then each message is rendered as
  "[<timestamp>] <Role>: <text>"  when a timestamp is present
  OR "<Role>: <text>"             when no timestamp is present
And messages are joined by a blank line
And role is title-cased (User, Assistant)
```

#### UC-CTE-7: Empty extraction signals "no mirror"

```
Given normalization yields an empty list
And a mirror already exists for that source_identity
When the session_mirrors service runs mirror generation
Then the existing mirror and its conversation text are left untouched
And the generation call reports "no conversation extracted"
And no mirror row is written

Given normalization yields an empty list
And no mirror exists for that source_identity
Then the row for that session_id and source_identity is cleared
And the generation call reports "no conversation extracted"

Given normalization yields fewer messages than the stored mirror's message_count
And the stored mirror already carries the current derivation version
When the session_mirrors service runs mirror generation
Then the stored mirror is kept unchanged
And the refusal is logged with the stored and parsed message counts
And the generation call reports "no conversation extracted"

Given normalization yields fewer messages than the stored mirror's message_count
And the stored mirror carries an older derivation version
When the current derivation intentionally removes non-conversation messages
Then the regenerated mirror replaces the stale conversation text
And the mirror advances to the current derivation version
And the generation call reports success
```

#### UC-CTE-8: Successful extraction upserts the mirror

```
Given normalization yields one or more messages
When the session_mirrors service runs mirror generation
Then timestamp_start is the first surviving message's timestamp
And timestamp_end is the last surviving message's timestamp
And message_count equals the number of normalized messages
And command, slug, and is_worker are persisted on the row
And the mirror is upserted; on update the created_at is preserved
And updated_at is set to the current UTC ISO timestamp
And the generation call reports success
```

#### UC-CTE-9: Async surface

```
Given a caller awaits the async mirror generation entry point
When the call resolves
Then the synchronous extraction and upsert ran off the caller's event loop
And the resolved outcome is identical to the synchronous variant
```

#### UC-CTE-10: Identity is read from the transcript, not its filename

```
Given a transcript is extracted
When its session id is derived
Then the id is read from the transcript's own contents
And for a claude transcript that value is the session UUID the file is named for
And for a codex transcript it is the thread id carried in the session_meta header
And for a legacy gemini chat it is the sessionId recorded in the file
And a derived value that is not a full UUID fails the derivation rather than being stored
And a subagent transcript never reaches derivation, because discovery and the session-end fanout drop it first
```

## Known caveats

- Machine-context stripping happens on user text only. An assistant message
  that quotes injected context verbatim retains the quote.
- Serialized-content unwrapping is keyed on the `[{'text': …}]` shape and runs
  only on user text. A row whose stored text is not that shape passes through
  untouched.
- The launch tags the extractor strips are removed from the rendered
  `conversation_text` only; nothing is read from them.
- A first-message title is derived only from user messages; a record-less
  transcript where the assistant spoke first (rare) yields an empty title.
- Stripping is bounded to the enumerated tagged blocks. An agent runtime that
  injects standalone, untagged documentation turns (e.g. a policy snippet as its
  own user message) leaves those turns intact, so a first-message title for a
  record-less transcript can fall on an injected doc heading. Classifying such
  turns by content is out of scope — the extractor keys on structural markers,
  never on what text means.
- A mirror written before the session record carried command and title keeps
  the classification, command, slug, and title it was written with when the
  record no longer exists; nothing re-derives those from text.
- Timestamp rendering uses the structured message timestamp as-is — no
  reformatting, no timezone conversion. Stored format is whatever the
  agent runtime's transcript provided.
- Message-count is the count of normalized messages (post-filter), not the
  count of raw structured blocks in the transcript.
- The role renderer title-cases only the first letter. Any role string
  outside {user, assistant} would render with only its first letter
  capitalized; the pre-filter eliminates other roles so this is not
  currently observable.
