---
description: "Invoking an external mail or calendar connector on a person's behalf: binding the invocation to one declared account, directing that person's state, and applying the personal-assistant prohibitions to what the invocation is determined to reach."
delivered_by:
  - personal-mail-tool-launcher
---

# Assistant Connector Invocation — Spec

## Required reads

- @docs/project/spec/domain/integration.md

## What it is

The behavioral contract for reaching an external mail or calendar connector on a
person's behalf. Every such invocation is bound to one mail account that person
has declared, is directed at that person's own connector state, and carries the
two prohibitions the personal-assistant conduct policy declares — no send the
person did not ask for, and no settings change.

The prohibitions are applied to what an invocation is determined to reach, so a
generic pass-through request is judged by the endpoint it reaches rather than by
its command name, and an invocation whose reach cannot be determined is refused
rather than attempted. The platform's connector vocabulary is translated into a
particular tool here and nowhere above.

How strong the resulting gate is depends on the connector. Where the connector's
own build or authorization grant refuses a gated effect outright, this contract
composes with that structural refusal and the gate holds whatever the invocation
looks like. Where it does not, the gate rests on determining reach from the
invocation itself, which is defeasible; such a connector is invoked only on the
terms its own doctrine sets.

The prohibitions belong to the conduct policy and the account declaration to the
configuration that owns person data. This contract owns neither; it owns what
happens at the boundary where an external connector is actually reached.

The two prohibitions do not reach equal strength. Settings are refused outright.
Sending is made impossible only where no person is established as present to
instruct; where one is, nothing published carries what that person asked for, so
the boundary records an attributable claim rather than preventing a false one.

**Business value:** a connector that isolates nothing will, on a missed
configuration, act as the wrong identity and leave one person's credentials
where another's assistant finds them. Placing account binding, state direction
and the two prohibitions at the one boundary where connectors are reached is
what prevents that, and it makes each connector's remaining exposure a stated
property of that connector rather than an unexamined one.

## Canonical fields

### Use cases

#### UC-ACI-1: An unresolved person refuses the invocation

```gherkin
Given no acting person is resolved for a connector invocation
When the invocation is made
Then it is refused before the connector runs
And the refusal states that no acting person was resolved
And no credential or connection state is created or modified anywhere
```

#### UC-ACI-2: An invocation not bound to a declared account is refused

```gherkin
Given a resolved person who has declared one or more mail accounts
When a connector invocation does not name which account it acts as
Then it is refused before the connector runs
And the refusal states that no account was named
And no account is chosen on the invocation's behalf, even where the person has declared only one
```

#### UC-ACI-3: A person's identity address is not a mailbox

```gherkin
Given a person whose identifying address is not among their declared mail accounts
When a connector invocation acts as that address on their behalf
Then it is refused before the connector runs
And the person remains resolvable as a person
```

#### UC-ACI-4: State is directed at the acting person's own store

```gherkin
Given a connector invocation for a resolved person
When it reads or writes credential or connection state
Then the state location and connection it is directed at are that person's own
And it is never directed at a default location instead
```

#### UC-ACI-5: An invocation is never directed at another person's stored state

```gherkin
Given two people whose assistants operate on the same machine
When a connector invocation is made on behalf of one of them
Then nothing it does writes to the state the other person's assistant established
```

#### UC-ACI-6: Sending is impossible where no one is present to ask for it

```gherkin
Given a connector invocation on a person's behalf where no person is established as present to instruct
When it would cause mail to leave — whether through the connector's own send, reply, or forward operation or a generic pass-through request reaching one of those endpoints
Then the connector runs unable to send at all
And no assertion carried by the invocation makes sending available
And no mail leaves
```

#### UC-ACI-7: A settings change is refused whether or not the command name shows it

```gherkin
Given a connector invocation on a person's behalf
When it would change account settings — whether through the connector's own settings operation or a generic pass-through request reaching a settings endpoint
Then it is refused before the connector runs
And the account's settings are unchanged
```

#### UC-ACI-8: Undeterminable reach is refused rather than attempted

```gherkin
Given a connector invocation on a person's behalf
When its reach with respect to sending or changing settings cannot be determined
Then it is refused before the connector runs
And the refusal states that the invocation's reach could not be determined
```

#### UC-ACI-9: An instructed send is carried out

```gherkin
Given a person has asked for a message to be sent
When a connector invocation sends it on their behalf
Then the send executes from that person's own store
And the message leaves
```

#### UC-ACI-13: A send by someone present carries an attributable claim

```gherkin
Given a connector invocation on behalf of a person established as present to instruct
When it would cause mail to leave
Then it proceeds only when it carries the acting agent's claim that the person asked for it
And that claim is recorded against the session that made it
And an invocation carrying no such claim does not send
```

## Known caveats

- Where a gate rests on determining reach from the invocation itself, an
  endpoint alias or encoding that is not recognized is read as reaching nothing
  gated, and the effect runs. UC-ACI-8 covers reach that is recognized as
  undeterminable; it cannot cover reach that is misread as harmless. This is why
  the strength of a gate is a property of the connector rather than of this
  contract.
- Directing a connector's state at a person's own location does not by itself
  confine that person's secrets: a connector may resolve an account from a store
  shared across the machine regardless of where its state is directed, which
  presents as isolation while providing none. This contract states direction and
  makes no confinement claim; confinement belongs to whoever owns the per-person
  secret store.

## See Also

- ~/.teleclaude/docs/personal/policy/assistant-conduct.md — the two prohibitions this contract applies, and the mandate rule that decides when a permitted write runs.
- docs/project/spec/feature/config/person-mail-accounts.md — the declaration this contract binds an invocation to.
- docs/project/spec/feature/agent_runtime/assistant-connector-access.md — why every route the platform provides for reaching a connector leads to this boundary.
