---
visibility: 'public'
description: 'Permission is answered per declared tier along three independent axes — whether the tier establishes an invocation context, whether its material participates in a surface, and whether it carries optional project subscriptions — so no tier inherits another tier default and no answer on one axis grants anything on another.'
delivered_by:
  - person-tier-homes
---

# Tier Permissions — Spec

## Required reads

- @docs/project/spec/domain/config.md
- @docs/project/spec/feature/config/tier-declaration.md

## What it is

Asking what is permitted at a root is three questions, not one, and each is
answered from that root's declared tier:

- **Invocation context** — whether the tier establishes a root that an agent or
  human can work from, so that configuration and documentation compose for
  invocations beneath it.
- **Surface participation** — whether the tier's material takes part in a given
  platform surface, such as documentation.
- **Project subscriptions** — whether the tier carries the optional per-project
  capability subscriptions that govern the code, docs, and agents plumbing.

The three are independent. An answer on one axis grants nothing on another: a
tier whose material participates in documentation does not thereby become an
invocation context, and an invocation context does not thereby acquire project
subscriptions. Every declared tier receives an answer on every axis, and no tier
inherits another tier's answers or another tier's defaults.

Per tier:

- A **project** is an invocation context, its material participates in the
  surfaces its subscriptions enable, and it is the one tier governed by optional
  project subscriptions. Those subscriptions and everything derived from them
  are specified in `project/spec/feature/config/project-capability-manifest.md`.
- A **person** is an invocation context. Its material participates in
  documentation, and it carries the permission to commit its own home content
  and to own projects of its own. It carries no project subscriptions and no
  project lifecycle behavior.
- A **company** is not an invocation context — invocation from within a company
  folder behaves as invocation with no context root, as the tier declaration
  contract establishes. Its material participates in documentation. It carries
  no project subscriptions.
- The **global** tier is the invocation context of last resort and owns the
  shared home history. It carries no project subscriptions.

A project root may sit inside a person's personal space. Resolution takes the
nearest declaration, so such a root is a project on every axis while the
enclosing person context continues to supply the acting identity. Ownership of
such a project follows from where it sits: it belongs to that person, and no
assignment mapping is consulted.

## Canonical fields

### Use cases

#### UC-TIERP-1: Every declared tier answers all three questions

```
Given a root carrying any valid tier declaration
When an agent asks whether the root is an invocation context, whether its material participates in a surface, and whether it carries project subscriptions
Then each question is answered from the declared tier
And no question fails with an error
And no answer is derived from where the root sits
```

#### UC-TIERP-2: A tier never inherits another tier's answers

```
Given a root whose declared tier is not the project tier
When an agent asks what that root permits
Then the answer states that tier's own permissions
And it reports no project subscription the tier does not carry
```

#### UC-TIERP-3: Participation on one axis grants nothing on another

```
Given a tier whose material participates in documentation
And whose declaration establishes no invocation context
When an agent invokes from a root carrying that declaration
Then the invocation behaves as invocation with no context root
And no project subscription or lifecycle behavior is available there
```

#### UC-TIERP-4: A person context commits its own home content

```
Given a root declaring itself a person configuration
When an agent asks what that root permits
Then the root is an invocation context
And committing its own home content is permitted
And its material participates in documentation
And no project subscription and no project lifecycle behavior is available there
```

#### UC-TIERP-5: A project inside a personal space is a project

```
Given a project declaration at a root inside a person's personal space
When an agent invokes from that project root
Then the invocation resolves to that project on every permission axis
And the enclosing person context supplies the acting identity
And the project is owned by that person with no assignment mapping consulted
```

## Known caveats

- This contract states which tier is asked which question and what each tier
  answers. What a project's subscriptions mean, how they are declared, and what
  plumbing each one gates remain owned by
  `project/spec/feature/config/project-capability-manifest.md`.
- Answering truthfully for a tier is not a grant. Any operation beyond what the
  tier model already establishes for the global, person, and company tiers
  requires its own product authority and is not conferred here.

## See Also

- ~/.teleclaude/docs/general/design/configuration-tiers.md — the tier model this contract composes with.
