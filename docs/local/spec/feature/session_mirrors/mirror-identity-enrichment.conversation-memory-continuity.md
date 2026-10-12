---
description: One conversation mirror belongs to one retained TeleClaude session and preserves the provenance of every transcript in its lineage.
---

# Mirror Identity Enrichment — Spec

## What it is

A conversation mirror is identified by its retained TeleClaude session. Agent
runtime publishes the session's identity facts and ordered native transcript
lineage; session mirrors consume those facts rather than deriving human
identity from transcript prose or reaching into another domain's storage.

Mirror generation resolves the full lineage and uses the existing conversation
chain reader and projector that session tailing uses. Each source is parsed by
its producing runtime. The mirror applies its conversation-only visibility
policy, retaining human and assistant conversational text while excluding tool
calls, tool results, reasoning and injected runtime instructions.

The mirror records the session's principal, home subject and owner, registered
project, title, launch facts, originating adapter facts and closure facts. Each
source keeps its native identity, path, producing runtime and position as
provenance. A native source change updates the same conversation mirror.
Attribution is lineage, not authorship
(`general/concept/lineage-vs-authorship`).

Missing source material or missing upstream facts never erase recorded history.
Stored text remains durable independently of source-file retention. Migration
and identifier compatibility follow
`local/projects/teleclaude/spec/feature/session_mirrors/session-id-namespaces`.

## Canonical fields

### Use cases

#### UC-MIE-1:

```gherkin
Given an operator's conversation spans several native transcripts
When its mirror is refreshed through either existing producer path
Then the operator can retrieve the ordered conversation through one TeleClaude identity
And each exchange retains its source provenance
And refreshing more than one source does not duplicate the full conversation
```

#### UC-MIE-2:

```gherkin
Given the platform has established the authority under which a session ran
When an authorized agent reads its mirror attribution
Then the mirror reports that established principal
And it reports no principal where the record establishes none
```

#### UC-MIE-3:

```gherkin
Given an operator's session ran in a registered project
When its mirror is written
Then the mirror carries the project the registry establishes for that session
And an unregistered working path does not invent a project
```

#### UC-MIE-4:

```gherkin
Given an operator can retrieve recorded conversation text and identity facts
When a refresh lacks an older source or an upstream fact
Then the recorded content and established facts remain preserved
And the refresh reports incomplete coverage instead of representing missing input as erased history
```

#### UC-MIE-5:

```gherkin
Given an operator's session was started with recorded launch and lineage facts
When the session is mirrored and later closes
Then its mirror preserves those launch facts and records the closure
And repeated observations of that closure do not create another conversation
```

#### UC-MIE-6:

```gherkin
Given an operator closes or soft-deletes a session
When the operator later retrieves its historical conversation
Then its mirror, identity and source lineage remain resolvable under the existing access rules
```

#### UC-MIE-7:

```gherkin
Given a historical transcript has no established TeleClaude association
When that retained history is associated with an archive session
Then the conversation remains retrievable through its original source identity
And no missing human attribution is inferred from its prose
```

### Cross-context references

- Agent runtime owns session retention, conversation selection and native
  transcript lineage.
- Identity owns history reach and principal resolution.
- The mirror reconciliation and fanout contracts own when refresh work runs.

## Known caveats

- A source may be unavailable for re-derivation while its stored conversation
  remains readable. That limitation stays explicit in coverage results.
- Coverage that names a missing source is still ready for readers once every
  source present on disk has been read under the current derivation rules: the
  missing source's retained content is all the conversation still holds from it.
  A present source that failed or is not yet read leaves coverage not ready.
- Existing source exclusions and history access rules apply to the unified
  mirror just as they apply to its inputs.
