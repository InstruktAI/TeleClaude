---
description: The operations a memory agent uses to keep the memories about one person current — list, add, update, retire — plus collecting business items as prospects and advancing a conversation's read point; open only to procedure agents.
delivered_by:
  - help-desk-idle-memory-cycle
---

# Memory Curation — Spec

## Required reads

- @docs/local/spec/domain/memory.md

## What it is

Memories about a person are kept current by a memory agent, never accumulated.
The agent reads a stretch of conversation, compares it with the person's current
memories, and changes them: it adds a new memory, updates one whose fact
changed, or retires one that no longer holds. What to keep is the agent's
judgment; memory owns the operations and the state they leave behind.

Every operation works within one **scope**: one person (their identity key) in
one memory namespace (a desk's, or the person's own home's). A memory is
**current** or **retired**. Retired memories leave startup context and search
but stay recorded. Nothing is deleted by curation.

Business items a conversation showed are collected as **prospects** for the home
that owns the desk. A prospect is a record in the memory store but not a memory:
it is raw material, never rendered as startup context, returned by search, or
listed with memories.

The agent also advances the conversation session's **read point** — how far its
conversation has been read — once its changes are made.

## Canonical fields

### Use cases

#### UC-MC1: A memory agent lists one person's current memories

```gherkin
Given a procedure agent and a scope of one person in one namespace
When it lists the memories of that scope
Then it receives every current memory of that person in that namespace
And no retired memory, no prospect, and nothing of any other person or namespace
```

#### UC-MC2: Adding, updating and retiring stay within the scope

```gherkin
Given a procedure agent working on one scope
When it adds a memory, updates one, or retires one
Then the change applies to that scope only
And an update or retirement of a memory outside that scope is refused
```

#### UC-MC3: Retired memories are out of use but kept

```gherkin
Given a memory that a memory agent retired
When startup context is rendered or memories are searched or listed for use
Then the retired memory is not included
And it remains recorded with the moment it was retired
```

#### UC-MC4: Business items are collected as prospects

```gherkin
Given a procedure agent that read a desk conversation
When it records a business item for the home that owns the desk
Then the item is kept as a prospect in that home's namespace, with the conversation it came from
And it is never rendered as startup context, returned by search, or listed with memories
```

#### UC-MC5: The read point advances only when asked

```gherkin
Given a conversation session and a procedure agent that finished its changes for a stretch of that conversation
When the agent advances the session's read point to the newest entry it read
Then a later read of that session starts after that entry
And a read point is never moved backwards
```

#### UC-MC7: A conversation's business items are collected once

```gherkin
Given a procedure agent that recorded business items from a desk conversation
And the conversation's read point was not advanced afterwards
When a procedure agent reads that stretch again
Then the scope of that conversation lists the prospects already recorded from it
And an item already among them is not recorded a second time
```

#### UC-MC6: Only procedure agents curate

```gherkin
Given a caller asking to list a scope for curation, add, update or retire a memory, record a prospect, or advance a read point
When the caller is not an agent the platform started for a procedure, under the system principal
Then the request is refused and nothing changes
```

### Cross-context references

- **agent_runtime** — the memory agents are procedure agents started by a
  conversation session's end
  (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-continuity`);
  the read point is a fact on the session record.
- **identity** — supplies the person's identity key and principal recorded with
  each memory, and decides who is a procedure agent under the system principal
  (`local/projects/teleclaude/spec/feature/memory/identity-key-ownership`).

## Known caveats

- **Memory does not judge.** It applies the changes it is asked for within a
  scope; deciding them is the agent's.
- **Saving a single observation is unchanged.** The existing save path keeps its
  behavior; curation is a separate set of operations.
- **Prospects wait for aggregation.** Collected business items accumulate until
  their aggregation exists; nothing reads them meanwhile.
