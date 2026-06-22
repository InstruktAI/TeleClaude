---
description: "Normalization rules that turn a structured agent transcript into the mirror's flat conversation_text and derived fields — user and assistant text only, injected machine-context (system-reminders, AGENTS.md, environment_context, command tags) stripped, title derived from the launching command's wrapper heading plus slug (or the first real user message for human sessions), an is_agent_spawn classification, and timestamps anchored on the first and last surviving messages."
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
user and assistant messages, strips embedded machine-context from user
text — `<system-reminder>` blocks, the injected `# AGENTS.md instructions
for …` block, `<environment_context>` blocks, and the
`<command-message>` / `<command-name>` / `<command-args>` launch tags —
discards messages that become empty after stripping, and renders the
remaining sequence as `[<timestamp>] <Role>: <text>` blocks joined by
blank lines (or `<Role>: <text>` when the message carries no timestamp).

Before stripping, the extractor inspects the raw turns for the command
that launched the session. A session dispatched through `sessions run`
carries its launch command injected into the transcript, so the spawn
fact is recoverable from the transcript alone — no live session record is
required (the record is ephemeral; the mirror is eternal). When a
lifecycle worker/orchestrator/integrator command is detected the mirror
is classified `is_agent_spawn`, and its title is reconstructed from the
command's wrapper heading and slug rather than from injected boilerplate.

Derived fields that come along with the text body:

- `command` — the detected launch command (e.g. `next-review-plan`), else null.
- `slug` — the launch command's argument, else null.
- `is_agent_spawn` — true when the launch command is a lifecycle worker/orchestrator/integrator command.
- `title` — for an agent spawn, the command's wrapper heading (or the humanized command name when no heading is mapped) plus `: <slug>` when a slug was extracted; otherwise the first user message's stripped text truncated at the first newline and then to 120 characters with `...` when longer.
- `timestamp_start` — the first surviving message's timestamp.
- `timestamp_end` — the last surviving message's timestamp.

An extraction that produces zero normalized messages signals to the caller
to delete any existing mirror and (in the worker path) record a tombstone
instead of writing a row.

## Canonical fields

### Use cases

#### Filter to text-only user/assistant messages

```
Given a structured transcript with mixed message types (text, tool_use, tool_result, thinking)
When the session_mirrors service normalizes the transcript
Then only messages of type "text" with role "user" or "assistant" survive
And tool blocks, thinking blocks, and tool_result blocks are excluded
```

#### Strip injected machine-context from user text

```
Given a user message text containing injected machine-context — one or more <system-reminder>...</system-reminder> blocks, a leading "# AGENTS.md instructions for ..." block, an <environment_context>...</environment_context> block, or <command-message>/<command-name>/<command-args> launch tags (each may span newlines)
When the extractor cleans the user text
Then every such injected block is removed in full
And the remaining text is whitespace-stripped
Given the cleaned user text is empty
Then the message is dropped from the normalized list
```

#### Assistant text passes through trimmed

```
Given an assistant message text
When normalization runs
Then the assistant text is whitespace-trimmed but otherwise unchanged
And no machine-context stripping is applied to assistant text
And an assistant message that trims to empty is dropped
```

#### Launch command detection and spawn classification

```
Given a normalized transcript before stripping
When the extractor scans the user turns for the launch command
Then it matches, in priority order:
  a claude marker "<command-name>/<cmd></command-name>" with slug from the adjacent "<command-args>...</command-args>"
  a codex/gemini loader "Read .../commands/<cmd>.md ..." with slug from the "provided inputs to that instruction set" tail
  a leading "/<cmd> <args>" at the start of a user line
And Claude Code builtins such as /clear, /model, /init are not treated as launch commands
And when the matched command is a lifecycle worker/orchestrator/integrator command the mirror is marked is_agent_spawn = true with command and slug recorded
And otherwise is_agent_spawn = false with command and slug null
```

#### Title derivation

```
Given a non-empty normalized message list
When the extractor derives the title
Then for an is_agent_spawn mirror the title is the detected command's wrapper heading, or the humanized command name when no wrapper heading is mapped, followed by ": <slug>" when a slug was extracted, else the heading alone
And for a non-spawn mirror the title is the first user message's stripped text, truncated at the first newline and then to 120 characters (right-trimmed) with "..." when longer
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
And command, slug, and is_agent_spawn are persisted on the row
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

- Machine-context stripping happens on user text only. An assistant message
  that quotes injected context verbatim retains the quote.
- Launch detection reads the raw turns before stripping; the command tags it
  keys on are removed from the rendered `conversation_text`.
- A non-spawn title is derived only from user messages; a session where the
  assistant spoke first (rare) yields an empty title.
- Slug extraction is best-effort. A worker launched with no parseable slug
  (e.g. a multi-argument review) yields a heading-only title.
- Timestamp rendering uses the structured message timestamp as-is — no
  reformatting, no timezone conversion. Stored format is whatever the
  agent runtime's transcript provided.
- Message-count is the count of normalized messages (post-filter), not the
  count of raw structured blocks in the transcript.
- The role renderer title-cases only the first letter. Any role string
  outside {user, assistant} would render with only its first letter
  capitalized; the pre-filter eliminates other roles so this is not
  currently observable.
