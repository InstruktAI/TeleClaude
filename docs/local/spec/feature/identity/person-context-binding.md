---
visibility: public
description: A person context is accepted as belonging to a registered person only
  when that binding is independently validated; an unknown, mismatched, or ambiguous
  claim fails closed and confers neither person-scoped visibility nor person-scoped
  write authority.
---

# Person Context Binding — Spec

## Required reads

- @docs/local/spec/feature/config/tier-declaration.md
- @docs/local/spec/feature/config/person-identity-schema.md

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

A validated binding is a published identity fact and nothing more. It is what
any person-scoped authority requires before it may be decided, never what
decides one: the surface that would act on a person's material owns whether it
acts, and reads this binding as an input. So validation grants nothing, and the
absence of a grant here is not an omission to be filled downstream by treating
the binding as permission.

The stakes are what make the failure path fail closed rather than warn. Every
person-scoped authority rests on this binding, so a claim accepted without
validation would carry each of them toward someone else's home. Inferring the
binding from where a directory sits would make any directory of the right shape
into an assertion of somebody's identity.

## Canonical fields

<!-- planned:issue-129 -->

### GitHub account association

The person's declared GitHub handle comes from that person's own overlay under
`local/projects/teleclaude/spec/feature/config/person-identity-schema`.
Identity first validates the context against exactly one registered person,
then compares the declared account's authenticated provider account facts with
the authenticated input account by stable provider account identifiers and
account type. Missing declarations, unresolved accounts, ambiguous person/home
claims, mismatches and bot-account claims establish no person binding
(`sdlc/policy/ai-agent-security`).

The handle is a human-facing declaration, not authentication evidence. Neither
an envelope nor its text, account lineage, a company/member credential profile
or a native login creates the association by inheritance. Binding validation
requires no person-home GitHub token and never selects a platform actor
(`sdlc/policy/ai-agent-security`).

A validated association is an identity fact, with no project authority or
decision authority attached. A human-account comment remains attributable to
its provider account; an unbound collaborator remains a collaborator. The
owning workflow resolves project authority and its outstanding named-person
question under
`local/projects/teleclaude/design/architecture/lifecycle-state-machines`, without
treating a declaration or matching account alone as that person's decision
(`general/policy/human-contract`).
<!-- /planned:issue-129 -->

### Use cases

#### UC-PCB-1: A validated binding is accepted

```
Given a root declaring itself a person configuration and naming a person
And that person is present in the person registry
When the binding is validated
Then the context is accepted as belonging to exactly that person
And that validated binding is published as an identity fact
And no visibility and no authority follow from the validation itself
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
