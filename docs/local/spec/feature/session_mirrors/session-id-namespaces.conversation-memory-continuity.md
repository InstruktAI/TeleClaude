---
description: TeleClaude session identity addresses one durable conversation mirror; native identities address its recorded transcript sources.
---

# Session Id Namespaces — Spec

## What it is

The TeleClaude session id identifies the lasting conversation and its one
mirror. The agent-native id identifies one producing runtime's transcript in
that conversation's lineage. Compaction, handoff and native transcript rotation
leave the TeleClaude identity stable.

Agent runtime owns the retained session record and publishes its ordered
transcript lineage. Session mirrors consume that lineage through the same
conversation projection used by session tailing. They store one complete
conversational projection per TeleClaude session. Source paths and native ids
remain provenance and exact source-retrieval aliases, not competing mirror keys
(`sdlc/policy/code-quality`).

## Canonical fields

### Addressing and migration

TeleClaude-id history retrieval returns the whole session conversation. Explicit
native-id or raw retrieval continues to identify the recorded source requested
by the caller, under the existing history reach checks. An ambiguous source
association is reported rather than silently joining different conversations.

Migration consolidates source mirrors through their recorded TeleClaude
attribution and lineage ordering, preserving conversation content, source
addresses and visibility facts. It restores a pruned session's retained identity
from established attribution where possible. Historical sources with no
TeleClaude association receive a retained, non-running archive session record;
only recorded facts are carried forward. No agent is launched and no person or
authority is invented by that archival association. Existing native-id history
references remain usable (`sdlc/policy/backward-compatibility-hygiene`).

### Use cases

#### UC-SIN-1:

```gherkin
Given an operator has a TeleClaude conversation containing native agent transcripts
When the operator inspects its identity
Then the conversation identity is distinct from the identities of its transcript sources
```

#### UC-SIN-2:

```gherkin
Given an operator's TeleClaude conversation spans several native transcripts
When the conversation is mirrored
Then it has one durable mirror addressed by its TeleClaude identity
And every source remains traceable within that mirror's provenance
```

#### UC-SIN-3:

```gherkin
Given an authorized caller supplies a full conversation or source identifier
When history resolves that identifier
Then a TeleClaude identifier addresses the complete conversation
And an explicit native identifier addresses its recorded source without bypassing history access rules
```

#### UC-SIN-4:

```gherkin
Given an agent supplies a malformed identity to historical retrieval
When the request is resolved
Then the identity is refused explicitly rather than matched by prefix or guessed recency
```

#### UC-SIN-5:

```gherkin
Given a runtime produced a subagent transcript
When the mirror producer encounters that source
Then the existing subagent exclusion applies
And no independent conversation mirror is created for it
```

#### UC-SIN-6:

```gherkin
Given historical mirrors include attributed and previously unattributed conversations
When storage migrates to retained TeleClaude conversation identities
Then every previously retained conversation remains retrievable
And existing source references still resolve under the same access rules
And missing authorship or identity facts remain unknown
```

## Known caveats

- Native transcript filenames remain provider-owned. The session's recorded
  lineage and source identity facts establish their association.
- Retaining the session record does not itself retain transcript bytes. The
  stored conversation mirror remains durable when a source file is unavailable.
