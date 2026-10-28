---
description: Conversation-only transcript projection with launch facts supplied by the owning session and preserved source provenance.
---

# Conversation Text Extraction — Spec

## Required reads

@docs/local/spec/domain/session_mirrors.md

## What it is

A mirror preserves searchable human and assistant conversation through the
shared conversation projector. Tool invocations, tool results, thinking,
injected platform instructions and compaction metadata are outside its
conversation text. Generation is deterministic and calls no language model
(`local/projects/teleclaude/spec/feature/session_mirrors/session-summary-generation`).

Each generation reads the retained TeleClaude session's complete ordered
transcript lineage through the same chain reader and projector as session
tailing. It updates the session's one conversational mirror. Native ids,
producing runtimes, paths and entry positions remain source provenance.

Launch command, focused-role classification, title and identity facts come from the
owning session under
`local/projects/teleclaude/spec/feature/session_mirrors/mirror-identity-enrichment`.
Conversation text never supplies launch authority. With no owning context, an
existing mirror keeps its recorded launch facts and title. A newly discovered
unattributed source can derive a display title from its first human message,
without inferring a launch command, focused role or human identity.

The projection removes structurally identified runtime content and trims the
remaining conversational messages. Empty messages are omitted. An empty or
unexpectedly shortened read preserves an existing mirror; a deliberate
projection-version change may re-derive stored rendering. Source coverage remains
separate from the agent's compacted working context.

## Canonical fields

### Use cases

#### UC-CTE-1: An operator reviews a session's conversation

```gherkin
Given an operator wants to review a session's conversation
When they read its mirror
Then each conversational message is available in source order with its speaker and recorded timestamp
And human and assistant text remains without tool calls, results, reasoning or injected platform instructions
And empty messages are omitted
And assistant response quotes remain while surrounding whitespace is removed
```

#### UC-CTE-2: An operator sees human conversation without injected instructions

#### UC-CTE-3: An operator can read an assistant reply with its quoted content

#### UC-CTE-4:

#### UC-CTE-5:

#### UC-CTE-6: An operator can follow who said what and when

#### UC-CTE-7:

#### UC-CTE-8:

#### UC-CTE-9:

#### UC-CTE-10: An operator can identify the mirror's source

```gherkin
Given an operator is investigating a mirrored conversation
When they inspect its provenance
Then they can identify the source transcript
```

## Known caveats

- Assistant-authored quotations remain conversational text, even when they quote
  platform instructions.
- Structural provenance determines which source spans are runtime content. Text
  without such provenance is not classified by its apparent meaning.
- A first-human-message fallback title is display text for a newly unattributed
  source; it establishes no launch facts or person identity.
- Source timestamps retain their recorded representation. Message counts describe
  the projected conversation rather than all raw runtime records.
- Coverage and preservation under missing source files follow the mirror identity
  and reconciliation contracts; successful parsing of a suffix alone does not
  establish completeness of an earlier conversation.
