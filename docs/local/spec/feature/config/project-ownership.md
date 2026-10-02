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
<!-- planned:personal-assistant-project-creation -->
- A person may declare themselves the owner of a project they adopt, at
  adoption and only for themselves: the declaration names the adopting person
  and no one else, and it never replaces an owner already declared.
<!-- /planned:personal-assistant-project-creation -->

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

<!-- planned:personal-assistant-project-creation -->
#### UC-POWN-6: A person declares themselves owner when adopting a project

```gherkin
Given a registered person adopts a folder that declares no owner
And they ask adoption to record them as its owner
When the project's owner is resolved
Then the owner is that person
And adopting it again with the same request leaves the declaration unchanged
```

#### UC-POWN-7: Adoption never reassigns a declared owner

```gherkin
Given a folder whose configuration declares an owner
When a different person adopts it and asks to be recorded as its owner
Then the adoption is refused, naming the declared owner
And the declared owner is unchanged
```

<!-- /planned:personal-assistant-project-creation -->
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
