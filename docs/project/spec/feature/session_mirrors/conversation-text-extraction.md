---
description: "Normalization rules that turn a structured agent transcript into the mirror's flat conversation_text and derived fields — user and assistant text only, injected machine-context (system-reminders, AGENTS.md, environment_context, command tags) stripped, title derived from the launching command's wrapper heading plus slug (or the first real user message for human sessions), an is_worker classification, and timestamps anchored on the first and last surviving messages."
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

Before stripping, the extractor inspects the raw turns for the command
that launched the session. A session dispatched through `sessions run`
carries its launch command injected into the transcript, so that fact
is recoverable from the transcript alone — no live session record is
required (the record is ephemeral; the mirror is eternal). A detected command that
names a real deployed artifact or a mapped lifecycle role reconstructs the title
from that command's wrapper heading and slug rather than from injected
boilerplate; the mirror is classified `is_worker` only when that command is a
dispatched worker. The two are independent: an orchestrator session gets its
command-derived title and stays searchable.

Derived fields that come along with the text body:

- `command` — the detected launch command (e.g. `next-review-plan`), else null.
- `slug` — the launch command's argument, else null.
- `is_worker` — true when the lifecycle command-role map marks the launch command a worker; false for an orchestrator, tasker, integrator, or a command the map does not carry.
- `title` — when the detected command names a deployed artifact or a mapped lifecycle role, that command's wrapper heading (or the humanized command name when no heading is mapped) plus `: <slug>` when a slug was extracted; otherwise the first user message's stripped text truncated at the first newline and then to 120 characters with `...` when longer.
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
Given a structured transcript with mixed message types (text, tool_use, tool_result, thinking)
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

#### UC-CTE-4: Launch command detection and worker classification

```
Given a normalized transcript before stripping
When the extractor scans the user turns for the launch command
<!-- planned-change:command-migration-to-singular-telec-skill -->

Then it matches, in priority order:
  a claude marker "<command-name>/<cmd></command-name>" with slug from the adjacent "<command-args>...</command-args>"
  a codex/gemini loader "Read .../commands/<cmd>.md ..." with slug from the "provided inputs to that instruction set" tail
  a leading "/<cmd> <args>" at the start of a user line
And Claude Code builtins such as /clear, /model, /init are not treated as launch commands

<!-- change:command-migration-to-singular-telec-skill -->

Then it matches, in priority order:
  a TeleClaude loader marker "TELECLAUDE COMMAND: <cmd> [<args>]" at the start of a user line, with slug from the first argument token
  a claude marker "<command-name>/<cmd></command-name>" with slug from the adjacent "<command-args>...</command-args>" (historical transcripts)
  a codex/gemini loader "Read .../commands/<cmd>.md ..." with slug from the "provided inputs to that instruction set" tail (historical transcripts)
  a leading "/<cmd> <args>" at the start of a user line (historical transcripts)
And the historical detectors are preserved unchanged so transcripts recorded before the marker existed derive identically
And a derivation-version bump gates fleet-wide re-derivation
And Claude Code builtins such as /clear, /model, /init are not treated as launch commands

<!-- /planned-change:command-migration-to-singular-telec-skill -->
And any matched command is recorded with its slug, whatever role that command carries
And the mirror is marked is_worker = true only when the lifecycle command-role map marks that command a worker
And a matched orchestrator, tasker or integrator command is recorded with is_worker = false
And when no command matched, is_worker = false with command and slug null
```

#### UC-CTE-5: Title derivation

```
Given a non-empty normalized message list
When the extractor derives the title
Then for a mirror whose detected command names a deployed command artifact or a mapped lifecycle role the title is that command's wrapper heading, or the humanized command name when no wrapper heading is mapped, followed by ": <slug>" when a slug was extracted, else the heading alone
And this holds whatever role the command carries, so an orchestrator mirror keeps its command-derived title while staying searchable
And for a mirror whose detected command names no such artifact or role the title comes from the first user message, so a spurious match keeps the human's own words
And for a mirror with no detected launch command the title is the first user message's stripped text, truncated at the first newline and then to 120 characters (right-trimmed) with "..." when longer
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
When the session_mirrors service runs mirror generation
Then the stored mirror is kept unchanged
And the refusal is logged with the stored and parsed message counts
And the generation call reports "no conversation extracted"
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
```

<!-- planned:history-search-canonical-conversation-results -->
#### UC-CTE-11: The mirror contains only the semantic conversation

```gherkin
Given an agent transcript contains authored conversation alongside runtime-provided startup context, command briefs, skill or instruction catalogs, AGENTS instructions, or environment metadata
When the session mirror derives its searchable conversation
Then only the authored human and agent conversation is retained
And runtime-provided context is absent from the mirror regardless of how the agent runtime represents it
And terms that occur only in runtime-provided context cannot make the conversation match history search
```
<!-- /planned:history-search-canonical-conversation-results -->

## Known caveats

- Machine-context stripping happens on user text only. An assistant message
  that quotes injected context verbatim retains the quote.
- Serialized-content unwrapping is keyed on the `[{'text': …}]` shape and runs
  only on user text. A row whose stored text is not that shape passes through
  untouched.
- Launch detection reads the raw turns before stripping; the command tags it
  keys on are removed from the rendered `conversation_text`.
- Detection keys on structural markers, so a leading slash in prose or a pasted
  path (`/Users/…`, `/bin`) can record a `command` for a session nothing
  launched. This never affects whether a conversation is stored or searchable:
  such a name carries no worker role, so the row keeps `is_worker = false` and
  stays visible. Only the title could be affected, and the deployed-artifact
  check above is what keeps it from becoming a humanized path fragment.
- A first-message title is derived only from user messages; a session where the
  assistant spoke first (rare) yields an empty title.
- Stripping is bounded to the enumerated tagged blocks. An agent runtime that
  injects standalone, untagged documentation turns (e.g. a policy snippet as its
  own user message) leaves those turns intact, so a first-message title can fall on
  an injected doc heading. Classifying such turns by content is out of scope —
  the extractor keys on structural markers, never on what text means.
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
