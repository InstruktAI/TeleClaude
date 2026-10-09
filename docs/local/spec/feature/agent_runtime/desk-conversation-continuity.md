---
description: A help-desk conversation outlives the session that carries it — an idle desk session is closed only after its memories are extracted and its context compacted, and its agent resumes with what it learned about that visitor at that desk.
delivered_by:
  - help-desk-idle-memory-cycle
---

# Desk Conversation Continuity — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

A desk session is closed only to spare resources while its visitor is away,
never to end the conversation. Once a desk session has had no input for 30
minutes, the daemon extracts what the conversation taught about the visitor and
about the desk's business, compacts the agent's context, and closes the session.
The visitor's next message, or their re-entry at the desk, revives the same
session (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`),
and its agent starts with the memories recorded about that visitor at that desk.

Memories about a visitor are kept per desk and per visitor:

- A registered person is remembered as that person, whichever adapter they
  write from.
- Anyone else is remembered by the platform identity they wrote from (their
  Discord user, Telegram user or WhatsApp number).

Business observations drawn from desk conversations belong to the home that
owns the desk and reach that home's own sessions, never a visitor's session.

Sessions that are not at a help desk are never closed by this cycle.

## Canonical fields

### Use cases

#### UC-DCC1: An idle desk session is closed after extraction and compaction

```gherkin
Given a desk session whose agent is idle
And the session has received no input for 30 minutes
When the daemon's idle cycle reaches it
Then the conversation since the last extraction is extracted into memories first
And the agent's context is compacted only after that extraction completed
And the session is closed only after the compaction completed
And the visitor receives no message about any of it
```

#### UC-DCC2: A failed extraction leaves the session as it was

```gherkin
Given a desk session that is due for its idle cycle
When extracting its conversation fails
Then the session is neither compacted nor closed
And the next pass of the idle cycle tries again from the same point in the conversation
```

#### UC-DCC3: A conversation that is still going on is not closed

```gherkin
Given a desk session that would otherwise be due for its idle cycle
When its agent is still working, an escalation relay is active on it, or input reached it after the cycle began
Then the session is not compacted or closed by that pass
And the escalation, the agent's work and the new input continue undisturbed
```

#### UC-DCC4: A revived desk session starts with what it learned about its visitor

```gherkin
Given a desk session closed by the idle cycle
And memories were extracted from its conversation
When the visitor writes again or re-enters the desk, and the session is revived
Then the revived agent's startup context holds the memories recorded about that visitor at that desk
And it holds no memory recorded about any other visitor or at any other desk
```

#### UC-DCC5: A registered person is remembered across adapters

```gherkin
Given a registered person who talked to a desk from one adapter
When the same person later writes to that desk from another adapter
Then the session serving them starts with the memories recorded about them at that desk
```

#### UC-DCC6: An unregistered visitor is remembered by the identity they wrote from

```gherkin
Given a visitor the platform does not know as a registered person
When their memories are recorded at a desk
Then they are recorded under the platform identity the visitor wrote from
And a later session at that desk serving the same platform identity starts with them
And a session serving any other identity does not
```

#### UC-DCC7: Business observations stay with the desk's home

```gherkin
Given a desk conversation that taught something about the business — a request, a complaint, a recurring confusion
When its memories are extracted
Then that observation is recorded for the home that owns the desk
And it reaches the sessions of the people who work in that home
And it never appears in the startup context of a visitor's session
```

#### UC-DCC8: Every conversation is extracted once

```gherkin
Given a desk session whose conversation was extracted up to some point
When the idle cycle extracts it again, after a later idle period, a failed attempt, or a daemon restart
Then only the conversation after that point is extracted
And no memory is recorded twice for the same part of the conversation
```

#### UC-DCC9: A desk session closed some other way is still extracted

```gherkin
Given a desk session that was closed by someone or something other than the idle cycle
And part of its conversation was never extracted
When the idle cycle next runs
Then that part of the conversation is extracted into memories
And the session stays closed
```

#### UC-DCC10: Only desk sessions are closed for being idle

```gherkin
Given a session that is not at a help desk, such as a person's assistant or an agent's worker
When it has had no input for 30 minutes or longer
Then the idle cycle neither extracts, compacts nor closes it
```

### Cross-context references

- **memory** — stores the extracted observations and renders them as startup
  context (`local/projects/teleclaude/spec/feature/memory/memory-context-injection`);
  the per-visitor narrowing is memory's opaque identity scope
  (`local/projects/teleclaude/spec/feature/memory/identity-key-ownership`).
- **identity** — decides who a visitor is (a registered person or a platform
  identity) and which observations a visitor's session may receive
  (`local/projects/teleclaude/spec/feature/identity/data-visibility`).
- **agent_runtime** — closing and reviving the session follow the session
  surfaces (`local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle`,
  `local/projects/teleclaude/spec/feature/agent_runtime/session-revival`).

## Known caveats

- **Closing happens on the cycle's next pass, not at the 30-minute mark.** The
  idle cycle runs periodically, so a session closes within one pass after its
  threshold.
- **A session whose agent never returns to idle is never closed by this
  cycle.** The cycle compacts only an idle agent, and it closes only a
  compacted session.
- **A session whose extraction keeps failing stays open.** Memories are never
  traded for resources; the session remains until an extraction succeeds or
  someone closes it.
- **Extraction is an agent session of its own.** The daemon starts an
  extraction worker for each stretch of conversation and waits for its pass
  across later passes of the cycle, so a session closes some passes after it
  became due; a cap on concurrently running workers can delay it further.
- **Compaction is the agent's own.** Only agents that can serve a desk run the
  cycle, and those are the agents with a verified desk confinement.
