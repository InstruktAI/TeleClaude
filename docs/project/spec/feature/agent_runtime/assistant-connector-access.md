---
description: "How an agent session reaches a person's mail and calendar connectors: a mediated launch that binds every invocation to one resolved person's store and applies the two personal-assistant prohibitions to what each invocation is determined to reach, composing with whatever the connector itself refuses."
delivered_by:
  - personal-mail-tool-launcher
---

# Assistant Connector Access — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The behavioral contract for how an agent session acting as someone's assistant
reaches the mail and calendar connectors. An agent never touches a connector
binary directly, and no route available to an agent session reaches one except
this boundary: an invocation arrives at a mediated launch that consumes the
resolved acting person, binds the connector's credential and connection
state to that person alone, and applies the two prohibitions the
personal-assistant conduct policy declares — no send the person did not ask
for, and no settings change. It applies them to what an invocation is
determined to reach, so a generic pass-through request is judged by the
endpoint it reaches rather than by its command name, and an invocation whose
reach cannot be determined is refused rather than attempted.

How strong the resulting gate is depends on the connector. Where the
connector's own build or authorization grant refuses a gated effect outright,
this boundary composes with that structural refusal and the gate holds
whatever the invocation looks like. Where it does not, the gate rests on
determining reach from the invocation itself, which is defeasible; such a
connector is fronted only on the terms its own doctrine sets.

The boundary enforces two prohibitions and nothing more. Which permitted
operations an assistant should reach for is connector doctrine, owned in the
personal domain; an invocation that is neither send-reaching nor
settings-reaching passes this boundary and remains governed by that doctrine
and by the conduct policy's mandate rule.

**Business value:** the conduct policy promises that its gates are enforced
where the tool runs. Connectors differ in what they enforce for themselves, and
one that isolates nothing will, on a missed configuration, write one person's
credentials into another's store and act as the wrong identity. Placing
resolution and the two gates at the single launch boundary makes the promise
true for every connector the platform fronts, so adopting a new one becomes a
doctrine question rather than a safety question.

## Canonical fields

### Use cases

#### UC-ACA-1: An unresolved person refuses the invocation

```gherkin
Given an agent session in which no acting person is resolved
When the session invokes a fronted connector
Then the invocation is refused before the connector runs
And the refusal states that no acting person was resolved
And no credential or connection state is created or modified anywhere
```

#### UC-ACA-2: Connector state stays inside the acting person's own store

```gherkin
Given an agent session acting as a resolved person
When the session invokes a connector operation that reads or writes credential or connection state
Then that state is read and written only within that person's own store
And no state is left in a shared or default location
And no other person's stored state is changed
```

#### UC-ACA-3: A send the person did not ask for does not leave

```gherkin
Given an agent session acting as a resolved person
And the person has not asked for anything to be sent
When the session invokes an operation that would cause mail to leave — whether the connector's own send, reply, or forward operation or a generic pass-through request reaching one of those endpoints
Then the invocation does not reach the connector
And the refusal states that no instruction to send was given
And no mail leaves
```

#### UC-ACA-4: A settings change is refused whether or not the command name shows it

```gherkin
Given an agent session acting as a resolved person
When the session invokes an operation that would change account settings — whether the connector's own settings operation or a generic pass-through request reaching a settings endpoint
Then the invocation is refused before the connector runs
And the refusal states that settings operations are unavailable
And the account's settings are unchanged
```

#### UC-ACA-5: Undeterminable reach is refused rather than attempted

```gherkin
Given an agent session acting as a resolved person
When the session invokes an operation whose reach with respect to sending or changing settings cannot be determined
Then the invocation is refused before the connector runs
And the refusal states that the invocation's reach could not be determined
```

#### UC-ACA-6: No route from an agent session reaches a connector outside the boundary

```gherkin
Given an agent session
When the session attempts to reach a fronted connector by any route available to it
Then the invocation reaches the connector only through the mediated launch
And the gates that launch enforces apply to it
```

#### UC-ACA-7: An instructed send is carried out

```gherkin
Given an agent session acting as a resolved person
And the person has asked for a message to be sent
When the session invokes the connector's send operation
Then the send executes from that person's own store
And the message leaves
```

#### UC-ACA-8: An invocation never selects another person's stored state

```gherkin
Given two people whose assistants operate on the same machine
When an agent session acting as one of them invokes a fronted connector
Then the invocation reads and writes only the state belonging to that person
And the state the other person's assistant established is neither read nor written
```

#### UC-ACA-9: Confining connectors keep one person's credentials unreadable by another

```gherkin
Given two people whose assistants operate under one operating-system account on the same machine
And the connector offers a secret store that can be confined to a single person
When an agent session acting as one of them invokes that connector
Then it cannot read the other person's stored credentials even when it seeks them
```

## Known caveats

- An unattended run is the case in which no instruction to send can exist, so
  nothing send-reaching runs there at all. Attendance is not itself authority to
  send; the instruction is.
- Whether a run is attended is established from the platform's own session
  context. Where it cannot be established the run is treated as unattended, so
  the send gate holds.
- Where a gate rests on determining reach from the invocation itself, an
  endpoint alias or encoding the boundary does not recognize is read as
  reaching nothing gated, and the effect runs. UC-ACA-5 covers reach that is
  recognized as undeterminable; it cannot cover reach that is misread as
  harmless. This is why the strength of a gate is a property of the connector
  and not of this boundary.
- Confinement of stored credentials is a property of the connector's secret
  store, not of where its state is routed. Routing state per person prevents an
  invocation from selecting another person's store (UC-ACA-8); it does not make
  plaintext credentials unreadable to a process running as the same
  operating-system user, which is what UC-ACA-9 requires a confining store for.

## See Also

- ~/.teleclaude/docs/personal/policy/assistant-conduct.md — the two gates this contract enforces and the mandate rule that decides when a permitted write runs.
- ~/.teleclaude/docs/personal/spec/tools/gog-cli.md — the permitted-operation doctrine for the Google connector.
- docs/project/spec/feature/agent_runtime/sealed-commit.md — the sibling mediated-tool contract on the same agent tool surface.
