---
visibility: public
description: A project's owner is its home's owner when the project lives in a person's or company's home, and a declared relationship — a company or a person, never both, and validly neither — when it lives outside every home.
---

# Project Ownership — Spec

## Required reads

- @docs/local/spec/feature/config/tier-declaration.md
- @docs/local/spec/feature/config/tier-permissions.md

## What it is

A project belongs to the owner of the home it lives in. A project inside a
person's home belongs to that person, and a project inside a company's home
belongs to that company. Nobody declares it: the home is the owner of record.

A home here is a person's or company's home at the location its registry
designates for it. A folder that merely declares itself a person or a company
is not a home, and confers no ownership on the projects beneath it. A person's
home is the one whose person-context binding identity accepts for that person
(`local/projects/teleclaude/spec/feature/identity/person-context-binding`). A
company's home is the one the company registry designates for that company.
The nearest such home above a project root is its owner's.

A project inside a home that declares an owner disagreeing with its home is not
a valid project configuration. A declaration that agrees with the home adds
nothing and is not required.

A project outside every home states whom it belongs to in its own
configuration. An owner there is a company or a person; the two are
alternatives, not layers. A project has at most one owner, and a declaration
naming both is refused rather than resolved by precedence. A project outside
every home may also name no owner at all; that is a valid, ordinary state and
not a defect to be repaired, and such a project composes no company
configuration.

An owner reference names a registered referent. A reference to a company or a
person that no registry knows is refused, so ownership never resolves to a
referent that does not exist. Refusal is the whole outcome: no partial owner is
recorded and no fallback owner is inferred.

A project's owner is resolved once, when its configuration is loaded, and the
loaded configuration carries the resolved owner. Every consumer reads that
answer and none reads the declaration directly. A resolved owner is never
written back into a project's configuration.

A new project outside every home is created with no owner; a company may then be
named as its owner. A person owner outside every home is kept where a project
already declares it and is never introduced: a change that adds or replaces a
person owner on a project outside every home is refused.

Owning a project carries authority over it. A person who owns a project holds
the administrator role on it, and a company that owns a project extends its
company roles to it, as `local/projects/teleclaude/design/architecture/scoped-roles`
resolves them. Every consumer that asks whose a project is reads this contract.

## Canonical fields

### Inside a home

- The owner is the home's owner, derived and never declared.
- The home is the nearest registry-designated person or company home above the
  project root.
- An owner declaration that disagrees with the home makes the configuration
  invalid.

### Outside every home

- Ownership is declared on the project, in the project's own configuration.
- The owner is either a registered company or a registered person, identified
  by that referent's stable reference key.
- Declaring no owner is valid and complete. An ownerless project composes no
  company configuration and acquires no owner from its location.
- A declaration naming both a company owner and a person owner is not a valid
  project configuration.
- A declaration naming an unregistered company or an unregistered person is
  refused.
- A person owner is kept where already declared and never introduced or
  replaced by a later change.

### Use cases

#### UC-POWN-1: A declared person owner is the project's owner

```gherkin
Given a project outside every home whose configuration declares a registered person as its owner
When the project's owner is resolved
Then the owner is that person
```

#### UC-POWN-2: A declared company owner keeps working

```gherkin
Given a project outside every home whose configuration declares a registered company as its owner
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

#### UC-POWN-5: An unregistered owner is refused

```gherkin
Given a project whose configuration declares an owner that no registry knows
When that configuration is loaded
Then loading fails with a clear result naming the unresolved owner
And the project is left with no owner rather than a partial one
```

#### UC-POWN-6: A project in a person's home belongs to that person

```gherkin
Given a project inside a registered person's home that declares no owner
When the project's owner is resolved
Then the owner is that person
```

#### UC-POWN-7: A project in a company's home belongs to that company

```gherkin
Given a project inside a registered company's home that declares no owner
When the project's owner is resolved
Then the owner is that company
And the project composes that company's configuration
```

#### UC-POWN-8: A declaration that disagrees with the home is refused

```gherkin
Given a project inside a registered person's home
And its configuration declares a different person or a company as its owner
When that configuration is loaded
Then loading fails with a clear result naming the home and the disagreeing declaration
And neither owner is selected
```

#### UC-POWN-9: A folder that only declares itself a home confers nothing

```gherkin
Given a folder outside every registry-designated home that declares itself a person's configuration
And a project beneath that folder that declares no owner
When the project's owner is resolved
Then the project has no owner
```

#### UC-POWN-11: A person owner is never introduced outside every home

```gherkin
Given a project outside every home that declares no owner, or declares a company
When an administrator changes its configuration to declare a person as its owner
Then the change is refused, naming the rule that person-owned projects live in their owner's home
And the project's owner is unchanged
```

#### UC-POWN-12: Adopting an existing project outside every home keeps its declared owner

```gherkin
Given an existing project outside every home that declares a registered person as its owner
And this machine has not adopted it yet
When it is adopted
Then its owner is that person
And its configuration is unchanged
```

#### UC-POWN-10: The owner of a project holds authority over it

```gherkin
Given a person who owns a project
And whose platform role is below administrator
When that person changes the project's configuration
Then the change is accepted
And another person who neither owns the project nor holds a role reaching it is refused the same change
```

## Known caveats

- What a project root permits — whether it is an invocation context, whether its
  material participates in a surface, and which subscriptions it carries — is
  answered from the declared tier and is owned by
  `local/projects/teleclaude/spec/feature/config/tier-permissions.md`.
- Who may work in a company's project is declared separately and owned by
  `local/projects/teleclaude/spec/feature/config/organizational-membership.md`.

## See Also

- ~/.teleclaude/docs/sdlc/policy/code-quality-practices.md — the structural-model rule under which a second simultaneous owner is excluded by the model rather than detected after the fact.
- docs/local/spec/feature/config/tier-permissions.md — the permission axes a project root answers, including a project that sits inside a home.
- docs/local/spec/feature/config/organizational-membership.md — project assignment, which states who may work in a company's project and never whose it is.
- docs/local/design/architecture/scoped-roles.md — the scopes through which ownership becomes authority.
