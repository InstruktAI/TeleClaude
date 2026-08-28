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
settings prohibition the personal-assistant conduct policy declares.

That prohibition is held by the connector's own controls: the invocation is
constructed so the connector permits only named operations and so its
authorization excludes the settings scopes. An operation outside the permitted
set does not run, whether or not the platform has seen it before. The platform's connector vocabulary is translated into a
particular tool here and nowhere above.

A connector is invoked only where it offers the controls this prohibition rests
on: an authorization grant that excludes the settings scopes and a permitted set
of operations the invocation is constructed with. A connector offering neither is
invoked on the terms its own doctrine sets.

The prohibitions belong to the conduct policy and the account declaration to the
configuration that owns person data. This contract owns neither; it owns what
happens at the boundary where an external connector is actually reached.

The two prohibitions do not reach equal strength. Settings are refused outright.
This contract governs the settings prohibition.

**Business value:** a connector that isolates nothing will, on a missed
configuration, act as the wrong identity and leave one person's credentials
where another's assistant finds them. Placing account binding, state direction
and the settings prohibition at the one boundary where connectors are reached is
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

#### UC-ACI-7: A settings change is refused whether or not the command name shows it

```gherkin
Given a connector invocation on a person's behalf
When it would change account settings — whether through the connector's own settings operation or a generic pass-through request reaching a settings endpoint
Then it is refused before the connector runs
And the account's settings are unchanged
```

#### UC-ACI-8: An operation outside the permitted set does not run

```gherkin
Given a connector invocation naming an operation the connector has not been permitted for this run
When the invocation is made
Then that operation does not execute
And this holds for an operation never seen before as well as one recognised as prohibited
```

## Known caveats

- The permitted set is what an operation must appear in to run, so an operation
  the platform has never seen is refused without anything having to recognise it
  as dangerous. Nothing here inspects an invocation to judge what it would reach.
- Directing a connector's state at a person's own location does not by itself
  confine that person's secrets: a connector may resolve an account from a store
  shared across the machine regardless of where its state is directed, which
  presents as isolation while providing none. This contract states direction and
  makes no confinement claim; confinement belongs to whoever owns the per-person
  secret store. What keeps one person's invocation away from another's credential
  is the account binding: stored secrets are keyed by address, and an invocation
  may name only an address the acting person declared.

## See Also

- ~/.teleclaude/docs/personal/policy/assistant-conduct.md — the two prohibitions this contract applies, and the mandate rule that decides when a permitted write runs.
- docs/project/spec/feature/config/person-mail-accounts.md — the declaration this contract binds an invocation to.
- docs/project/spec/feature/agent_runtime/assistant-connector-access.md — why every route the platform provides for reaching a connector leads to this boundary.
