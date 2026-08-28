---
visibility: public
description: A project's owner is a declared relationship on the project itself — a company or a person, never both, and validly neither — resolved from that declaration rather than from the directory that contains the project.
delivered_by:
  - person-tier-declarations
---

# Project Ownership — Spec

## Required reads

- @docs/project/spec/feature/config/tier-declaration.md
- @docs/project/spec/feature/config/tier-permissions.md

## What it is

A project states whom it belongs to. That statement is a declared relationship
carried by the project's own configuration, and it is the only thing that
establishes ownership: the directory a project sits in, the tier of any
enclosing root, and the repository that holds the project's history establish
nothing about who owns it.

An owner is a company or a person. The two are alternatives, not layers — a
project has at most one owner, and a declaration naming both is refused rather
than resolved by precedence. A project may also name no owner at all; that is a
valid, ordinary state and not a defect to be repaired, and such a project
composes no company configuration.

An owner reference names a registered referent. A reference to a company or a
person that no registry knows is refused, so ownership never resolves to a
referent that does not exist. Refusal is the whole outcome: no partial owner is
recorded and no fallback owner is inferred from the project's surroundings.

Ownership answers whose project this is. It does not answer who may work in it;
that is a separate declaration with its own contract, and neither settles the
other. Ownership likewise confers no permission of its own: what a project root
permits is answered from its declared tier.

Making a second simultaneous owner unrepresentable rather than merely
discouraged follows the structural-model rule in
`software-development/policy/code-quality-practices` — illegal states are
excluded by the model rather than detected after the fact, because a state that
can be written is a state some consumer will eventually read and resolve its
own way.

## Canonical fields

### The declaration

- Ownership is declared on the project, in the project's own configuration.
- The owner is either a registered company or a registered person, identified
  by that referent's stable reference key.
- Declaring no owner is valid and complete. An ownerless project composes no
  company configuration and acquires no owner from its location.
- A declaration naming both a company owner and a person owner is not a valid
  project configuration.
- A declaration naming an unregistered company or an unregistered person is
  refused.

### Use cases

#### UC-POWN-1: A declared person owner is the project's owner

```gherkin
Given a project whose configuration declares a registered person as its owner
When the project's owner is resolved
Then the owner is that person
And no part of the answer is derived from the directory containing the project
```

#### UC-POWN-2: A declared company owner keeps working

```gherkin
Given a project whose configuration declares a registered company as its owner
When the project's owner is resolved
Then the owner is that company
And the project composes that company's configuration
```

#### UC-POWN-3: An ownerless project stays ownerless

```gherkin
Given a project whose configuration declares no owner
When the project's owner is resolved
Then the project has no owner
And no owner is inferred from the root that contains it
And the project composes no company configuration
```

#### UC-POWN-4: Two simultaneous owners are not a valid declaration

```gherkin
Given a project configuration declaring both a company owner and a person owner
When that configuration is loaded
Then loading fails with a clear result naming the conflicting declaration
And neither owner is selected
```

#### UC-POWN-5: An unregistered owner is refused

```gherkin
Given a project whose configuration declares an owner that no registry knows
When that configuration is loaded
Then loading fails with a clear result naming the unresolved owner
And the project is left with no owner rather than a partial one
```

## Known caveats

- What a project root permits — whether it is an invocation context, whether its
  material participates in a surface, and which subscriptions it carries — is
  answered from the declared tier and is owned by
  `project/spec/feature/config/tier-permissions.md`. Ownership grants none of it.
- Who may work in a project is declared separately and owned by
  `project/spec/feature/config/organizational-membership.md`.

## See Also

- docs/project/spec/feature/config/tier-permissions.md — the permission axes a project root answers, including a project that sits inside a person's personal space.
- docs/project/spec/feature/config/organizational-membership.md — project assignment, which states who may work in a project and never whose it is.
