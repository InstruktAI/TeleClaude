---
description: "Read one session's stored record — a named session or the caller's own — as grouped diagnostic detail or as the complete record, under the same reach as listing, on any computer."
visibility: internal
delivered_by:
  - sessions-show
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

#### UC-SI1: A named session is shown as grouped diagnostic detail

```gherkin
Given an agent can list a session
When the agent inspects that session by its id
Then it receives that session's stored detail in one answer
And the detail is grouped as identity, origin, role, state, and wiring
And every value shown is one the session record stores
And no value the record does not store, such as a model name, an initial message, or command arguments, is shown
```

#### UC-SI2: The complete record is shown on request

```gherkin
Given an agent can list a session
When the agent inspects that session asking for the complete record
Then it receives every value the session record stores
And values the record stores as encoded structures are presented decoded
And the full text of the last output, the accepted-input comparison fingerprint, the help-desk relay exchange content, and the agent-status concurrency counter are left out
And the timestamps and digests that accompany the left-out values remain
```

#### UC-SI3: An agent inspects its own session without naming it

```gherkin
Given an agent running inside a TeleClaude session
When the agent inspects its own session without supplying an id
Then it receives the record of the session it runs in
```

#### UC-SI4: A caller that is not a session is told so

```gherkin
Given a caller at a terminal that is not a TeleClaude session
When the caller inspects its own session without supplying an id
Then the answer states that the caller is not a TeleClaude session
And the answer names the terminal identity the caller carries
And no record and no empty record is returned
```

#### UC-SI5: A session outside the caller's reach is refused with its door

```gherkin
Given a session exists that the caller's reach does not admit
When the caller inspects that session by its id
Then the caller is refused with an answer stating that the session is outside its reach
And the answer directs the caller to listing to see the sessions it can reach
And no part of the session's record is returned
```

#### UC-SI9: An id that matches no session is not found

```gherkin
Given no session carries the id a caller names
When the caller inspects that id
Then the caller receives a not-found answer
And the answer is distinct from the refusal for a session outside the caller's reach
```

#### UC-SI6: A retained closed session can be inspected

```gherkin
Given a session that has closed and is still retained
And the caller's reach admits it
When the caller inspects that session by its id
Then the caller receives its record, including when it closed
```

#### UC-SI7: A session on another computer is inspected through that computer

```gherkin
Given a session hosted on another computer
When an agent inspects that session naming that computer
Then that computer answers under its own reach for the agent's principal
And the agent receives the grouped detail, or the complete record when it asked for it
And a computer that cannot answer with the complete record makes the request fail explicitly rather than answer with less
```

#### UC-SI8: Help points to the neighbouring reads

```gherkin
Given an agent reads the help for session inspection
Then the help directs it to the transcript read for what a session said
And to listing for the roster and a session's children
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
