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

A conversation belongs to its durable TeleClaude session. A personal assistant
or help desk reached through a designated UI-adapter conversation channel
continues that session when its person returns. Continuing eligibility follows
the channel designation and resolved endpoint owned by
`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`.
It applies equally to direct chats and designated member-assistant channels.
Once the idle threshold is reached and the agent is idle, the daemon resumes the
recorded native transcript for compaction. Confirmed compaction completion
closes the runtime immediately, without another periodic wait. The threshold
is owned by `CONVERSATION_IDLE_THRESHOLD`.

A person may also explicitly start separate personal-assistant conversations.
Those use their ordinary session-close lifecycle rather than automatic idle
compaction. Creating one leaves the adapter-bound continuing conversation in
place. Both kinds are eligible for memory extraction at closure.
The person's next message, or their re-entry at the desk, revives the same
session (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`).
Adopting an existing session as that continuing conversation does not itself
start idle maintenance, close the session, or trigger memory extraction.

An eligible session closure requests readiness of its session-owned conversation
mirror. Only after the mirror covers that closure does the memory capability
release an extraction request. Readiness also succeeds when the existing mirror
already covers the conversation. Agent runtime supplies eligibility and the
closure identity; session mirrors supply coverage; memory owns extraction and
its completion (`sdlc/policy/code-quality`).

Eligibility covers human personal-assistant conversations and help-desk
conversations. Project SDLC sessions and autonomous task, procedure and worker
runs are outside this extraction lifecycle. The launch purpose and endpoint
establish the distinction; a working folder alone does not. Multiple PA
conversations retain independent source progress while contributing to the
person's same memory scope. The revived conversation receives its person's
current memories.

Memories about a person are kept per desk and per person:

- A registered person is remembered as that person, whichever adapter they
  write from; their own assistant remembers them in their own home.
- Anyone else is remembered at that desk by the platform identity they wrote
  from (their Discord user, Telegram user or WhatsApp number).

Sessions that are not conversation sessions are never compacted or closed by the
idle cycle; that includes every agent the platform starts for a procedure, the
memory agents among them, whose lifecycle is their procedure's own.

## Canonical fields

### Temporary compaction launches

The idle cycle resumes the conversation's recorded native transcript in a
temporary maintenance launch and submits the agent's declared compaction
command. The ordinary help-desk launch keeps native slash commands disabled
and bundled skills unavailable. Maintenance enables the compaction command
without widening the desk's other restrictions or changing the conversation's
identity, endpoint, memory scope or native transcript binding.

Returning conversation input or desk re-entry abandons maintenance immediately,
discards its tmux runtime through the existing shutdown machinery, and revives
the ordinary conversation through the existing transcript-resumption path.
Accepted input remains queued until that ordinary runtime can receive it, in
its accepted order; none reaches the maintenance launch. The person's return
resets the idle period, so the abandoned attempt waits for the next idle period.

Maintenance commands do not count as the person's input and produce no reply
to them. Maintenance startup and completion belong to their originating
attempt; a cancelled or superseded attempt neither opens the revived desk's
input readiness nor closes it. Abandoning a maintenance launch does not end the
conversation or trigger its memory agent. With no returning input, completed
compaction proceeds to the ordinary idle close and its session-ended behavior.

The platform uses its existing tmux shutdown and native transcript revival
contract. It neither rolls back a compaction already recorded by the agent nor
implements transcript validation or additional process-exit checks.

### Closure and continuation

The existing session record retains its endpoint, adapter metadata and ordered
native transcript lineage through closure and soft deletion. Compaction changes
the agent's working context; extraction reads the archived conversation rather
than that compacted context. Compaction-prompt customization follows the native
runtime contract and is separate from memory curation.

Closure readiness and extraction remain tied to the captured closure and
conversation coverage if the person returns before post-processing finishes.
New input resumes the same eligible conversation and forms later extractable
content. A mirror not yet ready for the closure leaves extraction pending with
an observable reason. Memory writes already completed survive an interrupted extraction.

### Use cases

#### UC-CC1: A person returns to their continuing conversation after time away

```gherkin
Given a person's designated assistant conversation has been idle while they were away
When they return and send a message
Then the same conversation resumes with its prior context
And they receive no maintenance message
```

#### UC-CC2: A conversation that is still going on is not closed

```gherkin
Given a person continues a designated conversation near its idle-close point
When the agent is still working, an escalation is active, or their input arrives during closure
Then their conversation remains available to continue
And the work, escalation, and accepted input continue undisturbed
```

#### UC-CC3: A closed conversation is read once by its memory agent

#### UC-CC4: Memories about a person stay current, not accumulated

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

#### UC-CC9: Only conversation sessions are closed for being idle

#### UC-CC10: A desk agent keeps native commands unavailable while serving its visitor

#### UC-CC11: A returning person abandons idle maintenance

```gherkin
Given a human person's conversation is undergoing idle compaction
When the person sends conversation input or re-enters their desk
Then the temporary compaction launch is abandoned without waiting for compaction to finish
And the ordinary agent resumes the same conversation
And accepted input reaches that ordinary agent in its accepted order, with none discarded or delivered to maintenance
And maintenance waits for the next idle period
```

#### UC-CC12: An abandoned attempt cannot affect the revived conversation

#### UC-CC13:

```gherkin
Given a human explicitly started an additional personal-assistant conversation
When that conversation reaches the idle interval
Then it retains its ordinary close lifecycle
And its eventual close receives the same mirror-based extraction as the person's continuing assistant
```

#### UC-CC14:

#### UC-CC15:

#### UC-CC16:

#### UC-CC17: A member's designated channel uses idle maintenance

#### UC-CC18: Adoption makes an existing channel conversation continuing

#### UC-CC19: Forum and explicit conversations retain ordinary closure

### Cross-context references

- **memory** — keeps the memories and their state, collects business items, and
  renders current memories as startup context
  (`local/projects/teleclaude/spec/feature/memory/memory-curation`,
  `local/projects/teleclaude/spec/feature/memory/memory-context-injection`).
- **identity** — decides who a person is (a registered person or a platform
  identity) and which memories a visitor's session may receive
  (`local/projects/teleclaude/spec/feature/identity/data-visibility`).
- **agent_runtime** — closing and reviving the session follow the session
  surfaces; memory agents are procedure agents reached by ready extraction requests
  (`local/projects/teleclaude/spec/feature/agent_runtime/procedure-standing-agent`).

## Known caveats

- Eligibility begins at the configured idle threshold. After native compaction
  completes, closure has no additional scan delay.
- **A session whose agent never returns to idle is never closed by this
  cycle.** The cycle compacts only an idle adapter-bound conversation and closes
  its runtime only after confirmed compaction.
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
