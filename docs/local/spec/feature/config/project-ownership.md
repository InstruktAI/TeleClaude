---
visibility: public
description: A project's owner is a declared relationship on the project itself —
  a company or a person, never both, and validly neither — resolved from that declaration
  rather than from the directory that contains the project.
---

# Project Ownership — Spec

## Required reads

- @docs/local/spec/feature/config/tier-declaration.md
- @docs/local/spec/feature/config/tier-permissions.md

## What it is

A project states whom it belongs to. That statement is a declared relationship
carried by the project's own configuration, and it is the only thing that
establishes ownership: the tier of any enclosing root and the repository that
holds the project's history establish nothing about who owns it.

A project inside a person's or a company's home declares that home's owner.
Creating or adopting a project there records it, and a configuration inside a
home that declares any other owner, or none, is refused. Outside every home the
declaration is free: a company, a person, or no owner.

An owner is a company or a person. The two are alternatives, not layers — a
project has at most one owner, and a declaration naming both is refused rather
than resolved by precedence. A project may also name no owner at all; that is a
valid, ordinary state and not a defect to be repaired, and such a project
composes no company configuration.

<!-- planned-change:missing-publisher-owner-surfacing -->

An owner reference names a registered referent. A reference to a company or a
person that no registry knows is refused, so ownership never resolves to a
referent that does not exist. Refusal is the whole outcome: no partial owner is
recorded and no fallback owner is inferred from the project's surroundings.

<!-- change:missing-publisher-owner-surfacing -->

An owner reference names a registered referent and resolves as
`local/projects/teleclaude/spec/feature/config/referent-resolution` states;
ownership never resolves to a referent that does not exist, no partial owner is
recorded, and no fallback owner is inferred from the project's surroundings.

<!-- /planned-change:missing-publisher-owner-surfacing -->

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
Given a project outside every home whose configuration declares no owner
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

<!-- planned-change:missing-publisher-owner-surfacing -->

#### UC-POWN-5: An unregistered owner is refused

```gherkin
Given a project whose configuration declares an owner that no registry knows
When that configuration is loaded
Then loading fails with a clear result naming the unresolved owner
And the project is left with no owner rather than a partial one
```

<!-- change:missing-publisher-owner-surfacing -->

#### UC-POWN-5: An unregistered owner is refused

<!-- /planned-change:missing-publisher-owner-surfacing -->

#### UC-POWN-6: A project inside a home is owned by that home

```gherkin
Given a project created or adopted inside a person's home
When the project's owner is resolved
Then the owner is that person
And the project's configuration declares that person
```

#### UC-POWN-7: A home refuses a project that names another owner

```gherkin
Given a project inside a company's home
And its configuration declares a different company, a person, or no owner
When that configuration is loaded
Then loading fails with a clear result naming the home and its owner
And no owner is selected
```

## Known caveats

- What a project root permits — whether it is an invocation context, whether its
  material participates in a surface, and which subscriptions it carries — is
  answered from the declared tier and is owned by
  `local/projects/teleclaude/spec/feature/config/tier-permissions.md`. Ownership grants none of it.
- Who may work in a project is declared separately and owned by
  `local/projects/teleclaude/spec/feature/config/organizational-membership.md`.

## See Also

- ~/.teleclaude/docs/sdlc/policy/code-quality-practices.md — the structural-model rule under which a second simultaneous owner is excluded by the model rather than detected after the fact.
- docs/local/spec/feature/config/tier-permissions.md — the permission axes a project root answers, including a project that sits inside a person's personal space.
- docs/local/spec/feature/config/organizational-membership.md — project assignment, which states who may work in a project and never whose it is.
