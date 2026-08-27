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
resolved acting person, binds the invocation to one mail account that person has
declared, directs the connector's credential and connection state at that
person's own store, and applies the two prohibitions the
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
resolution and the two gates at one boundary is what stops that, and it makes
each connector's remaining exposure a stated property of that connector rather
than an unexamined one — which is what adopting a new connector has to be
judged on.

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
Then the state location and connection the operation is directed at are that person's own
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

#### UC-ACA-8: An invocation is never directed at another person's stored state

```gherkin
Given two people whose assistants operate on the same machine
When an agent session acting as one of them invokes a fronted connector
Then the state location and connection the invocation is directed at are that person's own
And nothing the invocation does writes to the state the other person's assistant established
```

#### UC-ACA-9: Confining connectors keep one person's credentials unreadable by another

```gherkin
Given two people whose assistants operate under one operating-system account on the same machine
And the connector offers a secret store that can be confined to a single person
When an agent session acting as one of them invokes that connector
Then it cannot read the other person's stored credentials even when it seeks them
```

#### UC-ACA-10: An invocation not bound to a declared account is refused

```gherkin
Given an agent session acting as a resolved person who has declared one or more mail accounts
When the session invokes a fronted connector without naming which account it acts as
Then the invocation is refused before the connector runs
And the refusal states that no account was named
And no account is chosen on the invocation's behalf, even where the person has declared only one
```

#### UC-ACA-11: A person's identity address is not a mailbox

```gherkin
Given a person whose identifying address is not among their declared mail accounts
When an agent session acting as that person invokes a fronted connector as that address
Then the invocation is refused before the connector runs
And the person remains resolvable as a person
```

## Known caveats

- A person's declared mail accounts name a connector and an address, and the
  connector vocabulary is the platform's own rather than any vendor's, so
  nothing above this boundary names a vendor tool. The declaration belongs to
  the configuration that owns person data; this contract only consumes it.
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
- Direction and confinement are different guarantees. UC-ACA-8 settles where an
  invocation is aimed: its state location, its connection, and its writes are
  the acting person's. It says nothing about what the running process could
  reach by other means, because routing state per person cannot make plaintext
  credentials unreadable to a process running as the same operating-system
  user. Confinement is a property of the connector's secret store, and only a
  connector offering one satisfies UC-ACA-9.
- The accounts a person may act as are declared in the configuration that owns
  person data; this boundary consumes that declaration and never restates it.

## See Also

- ~/.teleclaude/docs/personal/policy/assistant-conduct.md — the two gates this contract enforces and the mandate rule that decides when a permitted write runs.
- ~/.teleclaude/docs/personal/spec/tools/gog-cli.md — the permitted-operation doctrine for the Google connector.
- docs/project/spec/feature/agent_runtime/sealed-commit.md — the sibling mediated-tool contract on the same agent tool surface.
