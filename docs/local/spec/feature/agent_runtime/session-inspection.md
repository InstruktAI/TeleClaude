---
description: Read one session's stored record — a named session or the caller's own
  — as grouped diagnostic detail or as the complete record, under the same reach as
  listing, on any computer.
visibility: internal
---

# Session Inspection — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

The read of a single session's stored record. Listing answers which sessions
exist and transcript retrieval answers what a session said; inspection answers
what one session is: its identity, who or what started it, the role it runs
under, the state it is in, and how it is wired to its pane, logs, and
transcripts. Its readers are agents and operators diagnosing a stall, a missed
delivery, or their own identity.

Inspection shows only what the record stores. It derives no value the record
does not hold, and it grants no visibility listing does not already grant.

## Canonical fields

### Use cases

#### UC-SI1: An operator can diagnose an authorized session

```gherkin
Given an operator needs to diagnose a session within their reach
When they inspect that session by its id
Then one answer shows the stored identity, origin, role, state, and wiring
And it includes no inferred values or conversation content
```

#### UC-SI2: An operator can request the complete stored session record

```gherkin
Given an operator needs the full stored record of a session within their reach
When they request its complete detail
Then they receive its stored values and decoded structures
And output text, input fingerprints, relay content, and concurrency counters remain excluded
And accompanying timestamps and digests remain available
```

#### UC-SI3: An agent can inspect its own session without naming it

```gherkin
Given an agent running inside a TeleClaude session
When the agent inspects its own session without supplying an id
Then it receives the record of the session it runs in
```

#### UC-SI4: A terminal operator can tell that no session is bound

```gherkin
Given an operator at a terminal that is not a TeleClaude session
When they ask to inspect their own session without supplying an id
Then the answer states that no TeleClaude session is bound
And it names the terminal identity they carry
And no record and no empty record is returned
```

#### UC-SI5: An operator receives a safe door for an out-of-reach session

```gherkin
Given a session exists outside an operator's reach
When they inspect that session by its id
Then inspection refuses and directs them to listing sessions they can reach
And no part of the inaccessible record is returned
```

#### UC-SI9: An operator can distinguish a missing session id

```gherkin
Given no session carries the id an operator names
When they inspect that id
Then they receive a not-found answer, distinct from an out-of-reach refusal
```

#### UC-SI6: An operator can inspect a retained closed session

```gherkin
Given an operator can reach a session that has closed and is still retained
When they inspect that session by its id
Then they receive its record, including when it closed
```

#### UC-SI7: A session on another computer is inspected through that computer

#### UC-SI8: Help points to the neighbouring reads

```gherkin
Given an agent needs a session's transcript or the session roster
When it asks for help with session inspection
Then help directs it to transcript retrieval for what the session said
And to listing for the roster and the session's children
```

### Cross-context references

- **identity** — the caller's reach decides which sessions inspection admits,
  exactly as for listing
  (`local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle`);
  a remote answer is decided by the hosting computer from the caller's relayed
  principal
  (`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`).
- **agent_runtime transcript retrieval** — owns what a session said; inspection
  leaves conversation content to it
  (`local/projects/teleclaude/spec/feature/agent_runtime/session-transcript-retrieval`).

## Known caveats

- **No children.** Inspection shows a session's own parent link and does not
  enumerate the sessions it started; listing answers that.
- **Reach refusals are explicit.** An out-of-reach session is refused as such
  and names listing as its door, rather than masked as not-found
  (`general/principle/trust-and-guardrails`).
