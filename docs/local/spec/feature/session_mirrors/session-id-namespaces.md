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

#### UC-SIN-2:

#### UC-SIN-3:

#### UC-SIN-4:

#### UC-SIN-5:

#### UC-SIN-6: A caller retains access to conversations after identity migration

```gherkin
Given a caller has conversation history from before mirror identity migration
When storage migrates those conversations to retained TeleClaude identities
Then the caller can retrieve every previously retained conversation under the same access rules
And existing source references still resolve
And missing authorship or identity facts remain unknown
```

## Known caveats

- Native transcript filenames remain provider-owned. The session's recorded
  lineage and source identity facts establish their association.
- Retaining the session record does not itself retain transcript bytes. The
  stored conversation mirror remains durable when a source file is unavailable.
