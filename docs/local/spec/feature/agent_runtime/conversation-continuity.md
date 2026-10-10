---
description: A help-desk or assistant conversation outlives the session that carries
  it — an idle conversation session is compacted and closed while its person is away,
  a memory agent keeps what the conversation taught about that person current, and
  the revived session starts with it.
---

# Conversation Continuity — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

A conversation session — a session at a help desk, or a session in a person's
own home that is that person's conversation with their assistant — is closed only to spare resources
while its person is away, never to end the conversation. Once it has had no input
for 30 minutes, the daemon compacts the agent's context and closes the session.
The person's next message, or their re-entry at the desk, revives the same
session (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`).

When the session ends, a memory agent reads what the conversation added since
it was last read and keeps the memories about that person current: it adds what
is new, updates what changed, and retires what no longer holds. At a desk it
also collects the business items the conversation showed, for the home that owns
the desk. The revived session starts with the current memories about its person.

Memories about a person are kept per desk and per person:

- A registered person is remembered as that person, whichever adapter they
  write from; their own assistant remembers them in their own home.
- Anyone else is remembered at that desk by the platform identity they wrote
  from (their Discord user, Telegram user or WhatsApp number).

Sessions that are not conversation sessions are never compacted or closed by the
idle cycle; that includes every agent the platform starts for a procedure, the
memory agents among them, whose lifecycle is their procedure's own.

## Canonical fields

### Use cases

#### UC-CC1: An idle conversation session is compacted, then closed

```gherkin
Given a conversation session whose agent is idle
And the session has received no input for 30 minutes
When the daemon's idle cycle reaches it
Then the agent's context is compacted
And the session is closed only after the compaction completed
And the person receives no message about any of it
```

#### UC-CC2: A conversation that is still going on is not closed

```gherkin
Given a conversation session that would otherwise be due for its idle close
When its agent is still working, an escalation relay is active on it, or input reached it while it was being closed
Then the session is not closed by that pass
And the escalation, the agent's work and the new input continue undisturbed
```

#### UC-CC3: A closed conversation is read once by its memory agent

```gherkin
Given a conversation session that ended, however it ended
When its end is announced
Then a memory agent reads the conversation after the point it last read, including what came before any compaction
And afterwards that point covers the conversation it read
And a later end of the same session is read from there, never from the beginning again
```

#### UC-CC4: Memories about a person stay current, not accumulated

```gherkin
Given current memories about a person, and a newly read stretch of conversation with them
When the memory agent keeps their memories
Then a new fact becomes a new memory
And a changed fact updates the memory that held it
And a fact that no longer holds retires its memory
And no near-duplicate of an existing memory is added
```

#### UC-CC5: A revived session starts with the current memories about its person

```gherkin
Given a conversation session that was closed while its person was away
When the person writes again or re-enters the desk, and the session is revived
Then the revived agent's startup context holds the current memories about that person, at that desk or in their own home
And it holds no retired memory, no memory about any other person, and none recorded at another desk
```

#### UC-CC6: A registered person is remembered across adapters

```gherkin
Given a registered person who talked to a desk from one adapter
When the same person later writes to that desk from another adapter
Then the session serving them starts with the memories recorded about them at that desk
```

#### UC-CC7: An unregistered visitor is remembered by the identity they wrote from

```gherkin
Given a visitor the platform does not know as a registered person
When memories about them are kept at a desk
Then they are kept under the platform identity the visitor wrote from
And a later session at that desk serving the same platform identity starts with them
And a session serving any other identity does not
```

#### UC-CC8: Business items from a desk conversation are collected, not used

```gherkin
Given a desk conversation that showed something about the business — a request, a complaint, recurring confusion, sentiment, a mention of an alternative
When its memory agent reads it
Then the item is collected for the home that owns the desk
And it never appears in any session's startup context
```

#### UC-CC9: Only conversation sessions are closed for being idle

```gherkin
Given a session that is not a conversation session, such as an agent's worker, an orchestrator, or a memory agent
When it has had no input for 30 minutes or longer
Then the idle cycle neither compacts nor closes it
```

### Cross-context references

- **memory** — keeps the memories and their state, collects business items, and
  renders current memories as startup context
  (`local/projects/teleclaude/spec/feature/memory/memory-curation`,
  `local/projects/teleclaude/spec/feature/memory/memory-context-injection`).
- **identity** — decides who a person is (a registered person or a platform
  identity) and which memories a visitor's session may receive
  (`local/projects/teleclaude/spec/feature/identity/data-visibility`).
- **agent_runtime** — closing and reviving the session follow the session
  surfaces; the memory agents are procedure agents started by the session's end
  (`local/projects/teleclaude/spec/feature/agent_runtime/procedure-standing-agent`).

## Known caveats

- **Closing happens on the cycle's next pass, not at the 30-minute mark.**
- **A session whose agent never returns to idle is never closed by this
  cycle.** The cycle compacts only an idle agent and closes only a compacted
  session.
- **A revived session continues its own conversation.** Revival resumes the
  session from its own transcript
  (`local/projects/teleclaude/spec/feature/agent_runtime/session-revival` UC-SR9),
  so the revived agent keeps the stretch before its last close, compacted. The
  memories its memory agent keeps from that stretch reach the session's later
  revivals and the person's other sessions.
- **Only agents with a compaction command are idle-closed.** Compaction is the
  agent's own command, observed through the agent's own end-of-compaction
  signal, both declared per agent. A conversation session running an agent
  without them stays open, as before. Help-desk dispatch offers only agents that
  declare them.
