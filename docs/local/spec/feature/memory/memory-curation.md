---
description: Identity-addressed curation of personal and desk memories from completed conversation mirrors, with independent source progress.
---

# Memory Curation — Spec

## What it is

A memory describes a person or visitor in a memory scope. Its identity is
independent of the conversation that supplied the evidence. Identity resolves
registered people to `person:<slug>` and unregistered visitors to their
provider-qualified entry identity. A person's personal memories and the
memories about that person at each help desk occupy separate scopes.

An extraction reads a bounded revision of one TeleClaude session's conversation
mirror. Its source references and progress identify what was processed; they
never select the person whose memories are changed. The memory worker judges
what the conversation establishes, compares it with current memories, and adds,
updates or retires observations. Business prospects belong to the desk's owner
and remain separate from person memories.

These boundaries follow explicit state ownership and identity resolution
(`sdlc/policy/code-quality`,
`local/projects/teleclaude/spec/feature/identity/human-identity-resolution`).

## Canonical fields

### Identity and scope

`--identity` accepts the canonical person key or a provider-qualified visitor
key. Identity validates and normalizes the supplied reference using the same
entry binding used at conversation entry. Verified bindings to registered people
resolve to their slug regardless of their role. Original provider metadata stays
available as provenance. Unlinked provider identities remain separate.

Without `--desk`, the identity names a registered person's personal memory
scope. With `--desk`, the existing help-desk identifier selects that desk's
memory scope. Unregistered visitors require a desk. Neither a working directory
nor a source session silently selects these values.

A verified visitor-to-person binding reconciles prior memories within the same
scope, preserving their provenance. Personal and desk scopes remain distinct.
Unscoped historical records are attributed only from reliable recorded evidence;
unresolved records remain retained and are excluded from automatic personal or
visitor context. General administrative history reach is unchanged.

### Worker command contract

```text
telec memories scope --identity <identity> [--desk <desk-id>]
telec memories add --identity <identity> [--desk <desk-id>] --extraction <id> --type <type> <text>
telec memories update <memory-id> --identity <identity> [--desk <desk-id>] --extraction <id> <text>
telec memories retire <memory-id> --identity <identity> [--desk <desk-id>] --extraction <id>
telec memories prospect --desk <desk-id> --extraction <id> --type <type> <text>
telec memories extraction read <id>
telec memories extraction complete <id>
telec memories extraction fail <id> --reason <reason>
```

The extraction assignment carries its resolved identity and scope. Mutations
verify that the named scope agrees with the assignment and preserve the source
reference. The existing observation-type vocabulary owns accepted types.
An extraction read returns its bounded conversational material, source coverage,
resolved scope, and already-recorded progress. Its content excludes tools,
reasoning, injected platform instructions, and compaction summaries.

Completion is the worker's declaration that its memory/prospect changes for the
supplied material are finished, including a successful run with no changes.
Completion advances durable progress only through that material. Failure keeps
the uncompleted stretch eligible and reports the reason. Reading, dispatching,
handing an event to a hook, and an agent stopping are not completion.

An extraction is released once its mirror's coverage is ready for the captured
closure. A source whose file has disappeared contributes its retained content,
and the extraction read names that source as missing. A present source that
cannot yet be read keeps the extraction pending with that reason.

Progress is independent for each TeleClaude conversation mirror and remains
stable through native transcript changes, compaction, and mirror re-derivation.
A timestamp alone on a person is never the progress key. Repeated delivery of
the same completed source revision does not repeat extraction. Updates for one
identity and memory scope are serialized, including work from different PA
conversations. A newer mirror revision cannot be overwritten by completion of
an older extraction.

Existing session-addressed curation calls have a deployment transition in which
they are normalized at the compatibility boundary. Worker instructions use the
identity-addressed contract. The transition preserves accepted work and ends
after pre-transition workers and fleet callers have moved to the current
contract (`sdlc/policy/backward-compatibility-hygiene`).

### Use cases

#### UC-MC1:

#### UC-MC2:

```gherkin
Scenario: A person's memories follow their conversation evidence
Given a person has a ready conversation extract
When memory curation completes that extract
Then their current memories reflect what the conversation establishes in that person's selected scope
And no other identity or scope is changed

Scenario: Separate conversations contribute to one personal memory
Given a person has several separate assistant conversations
When memory curation completes extracts from those conversations
Then each conversation can contribute evidence to the same personal memories
And completing one does not skip content from another
```

#### UC-MC3:

```gherkin
Given a person has retired an outdated memory
When an assistant provides current memory context or search results
Then the retired memory is absent from those results
And its historical observation remains recorded
```

#### UC-MC4:

```gherkin
Given a help desk owner wants a visitor's business opportunity captured
When the desk records that opportunity as a prospect
Then it belongs to the desk owner's prospect records
And it does not appear as a memory about the visitor
```

#### UC-MC5:

#### UC-MC6:

```gherkin
Given a caller asks to perform a memory-curation operation
When the platform has not established that caller as a procedure agent under its system authority
Then the operation is refused without changing memory or extraction progress
```

#### UC-MC7:

#### UC-MC8:

#### UC-MC9:

```gherkin
Given a person relies on memories from a conversation
When that source conversation is closed, removed, or continued with a different native transcript
Then the current memories remain tied to the same identity and scope
And their source remains traceable
```

#### UC-MC10:

```gherkin
Given a registered person has a verified binding from a provider identity
When they use the help desk where those visitor memories were created
Then the prior memories are available through the canonical person identity at that desk
And memories from other desks or providers remain unavailable
```

#### UC-MC11:

### Cross-context references

- Identity owns canonical person and visitor references and caller reach.
- Session mirrors own the complete conversation and its readable coverage
  (`local/projects/teleclaude/spec/feature/session_mirrors/mirror-detail-retrieval`).
- Agent runtime owns eligible conversation closure and procedure lifecycle
  (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-continuity`).

## Known caveats

- Content selection is the memory worker's judgment. The storage operations
  validate identity, scope and progress rather than grading its prose.
- A failed extraction can leave completed memory writes with unadvanced source
  progress. Retrying compares with current records before completing the stretch.
