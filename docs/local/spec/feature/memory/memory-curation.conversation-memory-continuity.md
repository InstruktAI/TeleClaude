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

```gherkin
Given a memory worker assigned to a person and memory scope
When it lists the current memories for that identity and scope
Then it receives that person's current memories in that scope
And it receives no retired memory, business prospect, or memory from another identity or scope
```

#### UC-MC2:

```gherkin
Given a memory worker processing an assigned conversation extract
When it adds, updates or retires a memory
Then the change is attributed to the assignment's person and memory scope
And a mismatching requested scope is refused without mutation
```

#### UC-MC3:

```gherkin
Given a memory worker retired a memory
When an assistant receives memory context or searches current memories
Then the retired memory is absent from that result
And the historical observation remains recorded
```

#### UC-MC4:

```gherkin
Given a desk memory worker found a business item in a visitor conversation
When it records that item as a prospect
Then the prospect belongs to the desk's owning home
And it does not appear as a person memory in assistant context or memory search
```

#### UC-MC5:

```gherkin
Given a memory worker finished handling a bounded conversation extract
When it declares the extraction complete
Then progress covers exactly the supplied stretch, whether or not any memory changed
And later extraction starts after that stretch
And progress never moves backwards
```

#### UC-MC6:

```gherkin
Given a caller asks to perform a memory-curation operation
When the platform has not established that caller as a procedure agent under its system authority
Then the operation is refused without changing memory or extraction progress
```

#### UC-MC7:

```gherkin
Given a desk memory worker recorded a prospect before an extraction was interrupted
When the same extract is handled again
Then the worker can see the prospect already recorded from that source
And handling the extract does not add that prospect again
```

#### UC-MC8:

```gherkin
Given a person has several separate personal-assistant conversations
When a memory worker completes extraction from one conversation
Then the other conversations retain their own extraction progress
And each can contribute observations to the same person's personal memories
```

#### UC-MC9:

```gherkin
Given an agent can retrieve a person's memories from an earlier conversation
When that source conversation is closed, soft-deleted, or continued with another native transcript
Then the memories remain attributed to the same identity and scope
And their recorded source remains traceable
```

#### UC-MC10:

```gherkin
Given a visitor has memories at a help desk under a provider identity
When identity verifies that provider account's binding to a registered person
Then an assistant serving that person at the same desk can retrieve those memories through the canonical person identity
And the binding does not expose memories from other desks or an unrelated provider identity
```

#### UC-MC11:

```gherkin
Given a worker completed extraction from a conversation revision
When a repeated notification or metadata-only mirror update reaches the worker
Then already processed conversational content is not mined again
And new conversational content remains eligible
```

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
