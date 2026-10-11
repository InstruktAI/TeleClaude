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

<!-- planned-change:conversation-memory-continuity -->

Each generation reads one native transcript. Its mirror is addressed by source
identity and carries the TeleClaude attribution available for that source.

<!-- change:conversation-memory-continuity -->

Each generation reads the retained TeleClaude session's complete ordered
transcript lineage through the same chain reader and projector as session
tailing. It updates the session's one conversational mirror. Native ids,
producing runtimes, paths and entry positions remain source provenance.

<!-- /planned-change:conversation-memory-continuity -->

Launch command, worker classification, title and identity facts come from the
owning session under
`local/projects/teleclaude/spec/feature/session_mirrors/mirror-identity-enrichment`.
Conversation text never supplies launch authority. With no owning context, an
existing mirror keeps its recorded launch facts and title. A newly discovered
unattributed source can derive a display title from its first human message,
without inferring a launch command, worker role or human identity.

The projection removes structurally identified runtime content and trims the
remaining conversational messages. Empty messages are omitted. An empty or
unexpectedly shortened read preserves an existing mirror; a deliberate
projection-version change may re-derive stored rendering. Source coverage remains
separate from the agent's compacted working context.

## Canonical fields

### Use cases

#### UC-CTE-1:

```gherkin
Given an agent retrieves a mirrored conversation whose source includes tools and reasoning
When the conversation is projected
Then human and assistant conversational messages are retained
And tool invocations, tool results and reasoning are absent
```

#### UC-CTE-2:

```gherkin
Given an agent retrieves a conversation containing runtime-injected instructions alongside human input
When the source is projected through its structural provenance
Then the human's conversation remains
And injected platform instructions are omitted
And an entry with no remaining conversational text contributes no message
```

#### UC-CTE-3:

```gherkin
Given an agent retrieves an assistant's conversational response
When the mirror renders that response
Then its text is preserved with surrounding whitespace removed
And quoted material inside that response remains part of the response
```

#### UC-CTE-4:

```gherkin
Given an operator retrieves an archived conversation with an established launch assignment
When its launch facts and worker classification are presented
Then they follow the assignment recorded by the platform for that session
And command-like text in the conversation does not change those facts
```

#### UC-CTE-5:

```gherkin
Given an operator has named a conversation
When its mirror is refreshed
Then the mirror presents the title established by the owning session
And a later refresh that supplies no title does not erase the recorded title
```

#### UC-CTE-6:

```gherkin
Given an agent reads a non-empty mirrored conversation
When the conversation is rendered
Then each message identifies its human or assistant speaker
And recorded message timestamps accompany their messages without time-zone rewriting
And messages remain separated in their recorded order
```

#### UC-CTE-7:

```gherkin
Given an operator can retrieve an existing conversation mirror
When a refresh produces no conversation or an unexpectedly shorter read under the same projection rules
Then the retained conversation remains readable
And the refresh does not claim that missing source content was erased from the conversation
```

#### UC-CTE-8:

```gherkin
Given an agent requests a mirror refresh with readable conversational content
When that refresh succeeds
Then the stored mirror contains the resulting conversation and its source coverage
And refreshing it preserves its original creation identity
```

#### UC-CTE-9:

```gherkin
Given an agent requests mirror generation through its asynchronous capability
When the request completes
Then it reports the same projection and persistence outcome as the synchronous capability
And source processing does not occupy the caller's event loop
```

#### UC-CTE-10:

```gherkin
Given an agent inspects the provenance of a mirrored conversation
When a native source identity is established
Then the producing transcript's recorded identity supplies that fact
And the source filename alone cannot establish or change it
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
