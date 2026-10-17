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
home that declares any other owner, or none, is refused with an error naming
the home and its owner. Outside every home the declaration is free: a company,
a person, or no owner.

An owner is a company or a person. The two are alternatives, not layers — a
project has at most one owner, and a declaration naming both is refused rather
than resolved by precedence. A project may also name no owner at all; that is a
valid, ordinary state and not a defect to be repaired, and such a project
composes no company configuration.

An owner reference names a registered referent and resolves as
`local/projects/teleclaude/spec/feature/config/referent-resolution` states;
ownership never resolves to a referent that does not exist, no partial owner is
recorded, and no fallback owner is inferred from the project's surroundings.

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
Given an operator wants a registered person to own a project
When they declare that person as the project's owner
Then the project belongs to that person regardless of its containing directory
```

#### UC-POWN-2: A declared company owner keeps working

```gherkin
Given an operator wants a registered company to own a project
When they declare that company as the project's owner
Then the project belongs to that company and composes its configuration
```

#### UC-POWN-3: An ownerless project stays ownerless

```gherkin
Given an operator wants a project outside every home to have no owner
When they leave its ownership declaration unset
Then the project remains ownerless and composes no company configuration
```

#### UC-POWN-4: Two simultaneous owners are not a valid declaration

```gherkin
Given an operator declares both a company and a person as one project's owner
When the project configuration is loaded
Then the conflicting declaration is rejected with a diagnostic naming both owner fields
And neither owner is selected
```

#### UC-POWN-5:

#### UC-POWN-6: A project inside a home is owned by that home

#### UC-POWN-7: A home refuses a project that names another owner

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
