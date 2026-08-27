---
visibility: 'public'
description: 'A person context is accepted as belonging to a registered person only when that binding is independently validated; an unknown, mismatched, or ambiguous claim fails closed and confers neither person-scoped visibility nor person-scoped write authority.'
delivered_by:
  - person-tier-homes
---

# Person Context Binding — Spec

## Required reads

- @docs/project/spec/feature/config/tier-declaration.md
- @docs/project/spec/feature/config/person-identity-schema.md

## What it is

A configuration file declaring itself a person configuration states what the
file is. It does not state that the person it names exists, and it does not
authenticate whoever is acting. Those are separate facts, and a context that
carries person-scoped authority needs all of them.

So a person context is accepted as belonging to exactly one registered person
only when that binding is independently validated against the person registry.
An unknown person, a claim that resolves to more than one person, and a claim
whose declared identity disagrees with the context it was found in each fail
closed: the failure is reported clearly, and the context receives neither
person-scoped visibility nor person-scoped write authority. Nothing degrades to
a partial grant.

The stakes are what make this fail closed rather than warn. A person context is
commit-capable over that person's own material, so a claim accepted without
validation carries write authority into someone else's home. Inferring the
binding from where a directory sits would make any directory of the right shape
into an assertion of somebody's identity.

## Canonical fields

### Use cases

#### UC-PCB-1: A validated binding is accepted

```
Given a root declaring itself a person configuration and naming a person
And that person is present in the person registry
When the binding is validated
Then the context is accepted as belonging to exactly that person
And person-scoped visibility and write authority follow for that person only
```

#### UC-PCB-2: An unregistered person fails closed

```
Given a root declaring itself a person configuration and naming a person absent from the person registry
When the binding is validated
Then validation fails with a clear result naming the unresolved person
And the context receives no person-scoped visibility and no person-scoped write authority
```

#### UC-PCB-3: An ambiguous or disagreeing claim fails closed

```
Given a root declaring itself a person configuration whose claimed identity resolves to more than one registered person, or disagrees with the context it was found in
When the binding is validated
Then validation fails with a clear result naming the conflict
And no person is selected
And the context receives no person-scoped visibility and no person-scoped write authority
```

#### UC-PCB-4: Declaring the tier does not authenticate the caller

```
Given a root declaring itself a person configuration whose binding validates
When the acting caller's own identity is resolved
Then the caller's identity is established independently of that declaration
And the declaration alone grants the caller no authority to act as that person
```
