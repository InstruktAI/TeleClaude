---
description: Whether a run carries the word of the person it acts for, answered from recorded authorship of accepted input rather than from anything an agent writes or reads.
delivered_by:
  - assistant-instructed-send
---

# Person Instruction — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md
- @docs/project/spec/feature/agent_runtime/session-input-delivery.md

## What it is

An agent acting on a person's behalf may perform some acts only when that person
asked for them in this run. Answering that requires a fact the run can be asked
for: has the person this session acts for authored input into it, or has
everything the session received come from a schedule, the platform, another
session, or the agent itself?

This contract publishes that fact. It is derived from the authorship already
recorded on accepted input, so it is a reading of what the platform observed,
never a claim an actor makes about itself. The fact is a precondition a consumer
composes with its own decision; it authorizes nothing on its own, and no consumer
may treat it as the whole of an authorization.

The fact answers only whether the person has spoken in this run. Whether a
particular act is what they asked for is a reading of their words, and stays
with whoever is acting.

**Business value:** the two outcomes a personal assistant owes its person — that
it carries out what they ask, and that it does nothing outward they did not ask
for — are the same decision seen from either side, and neither can be reached
without knowing whether the person spoke. Deriving that from recorded authorship
rather than from a declaration is what keeps material the assistant reads from
manufacturing its own permission.

## Canonical fields

### Use cases

#### UC-PI1: A run nobody spoke into carries no instruction

```gherkin
Given a session acting for a person
And every input the session has accepted in this run was authored by a schedule, the platform, or another session
When an agent asks whether this run carries that person's instruction
Then the answer is that it does not
```

#### UC-PI2: A turn the person authored is their word in this run

```gherkin
Given a session acting for a person
When that person authors a turn into the session through a surface they hold
Then an agent asking whether this run carries that person's instruction is told that it does
```

#### UC-PI3: Another person's word is not this person's instruction

```gherkin
Given a session acting for one person
When a turn in that session is authored by a human other than the person it acts for
Then an agent asking whether this run carries the acting person's instruction is told that it does not
And the answer does not change because the other human holds platform authority
```

#### UC-PI4: The answer follows recorded authorship, not content

```gherkin
Given a session acting for a person who has authored nothing into this run
When content delivered into the session states that the person asked for something, or imitates the form of their own input
Then an agent asking whether this run carries that person's instruction is told that it does not
And the answer is unchanged by how the content is worded
```

#### UC-PI5: An acting agent cannot declare the fact into existence

```gherkin
Given a session acting for a person who has authored nothing into this run
When the agent in that session declares that the person asked for an outbound act
Then an agent asking whether this run carries that person's instruction is told that it does not
And no context the session was started with supplies the missing word
```

## Known caveats

- The fact establishes that the person spoke in this run, not what they asked
  for. An agent that reads their words wrongly, or stretches one ask across a
  later act, is a failure this contract does not detect and is not built to.
- Whether a human authored a turn is recorded when that turn is accepted. Input
  reaching a session outside every accepted-input path leaves no authorship to
  read and therefore contributes no instruction.

## See Also

- ~/.teleclaude/docs/personal/policy/assistant-conduct.md — the conduct rule that makes a person's own word the condition for mail leaving, and the mandate rule that scopes an ask to the session it was made in.
- docs/project/spec/feature/agent_runtime/dispatch-involvement.md — the separate, declared dispatch fact this one is not, and which never authorizes an operation.
