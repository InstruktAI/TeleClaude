---
visibility: public
description: Permission is answered per declared tier along three independent axes
  — whether the tier establishes an invocation context, whether its material participates
  in a surface, and whether it carries optional project subscriptions — so no tier
  inherits another tier default and no answer on one axis grants anything on another.
---

# Tier Permissions — Spec

## Required reads

- @docs/local/spec/domain/config.md
- @docs/local/spec/feature/config/tier-declaration.md

## What it is

Asking what is permitted at a root is three questions, not one, and each is
answered from that root's declared tier:

- **Invocation context** — whether the tier establishes a root that an agent or
  human can work from, so that configuration and documentation compose for
  invocations beneath it.
- **Surface participation** — whether the tier's material takes part in a named
  platform surface. The surfaces this axis answers for are a closed set, and
  today that set is documentation alone. Adding a surface to it means stating
  every declared tier's answer for that surface; until then the axis has no
  answer to give for one, and none is inferred.
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
  are specified in `local/projects/teleclaude/spec/feature/config/project-capability-manifest.md`.
- A **person** is an invocation context. Its material participates in
  documentation. It carries no project subscriptions and no project lifecycle
  behavior.
- A **company** is not an invocation context — invocation from within a company
  folder behaves as invocation with no context root, as the tier declaration
  contract establishes. Its material participates in documentation. It carries
  no project subscriptions.
- The **global** tier is the invocation context of last resort and owns the
  shared home history. Its material participates in documentation, which is what
  makes global documentation readable from every context. It carries no project
  subscriptions.

A project root may sit inside a person's personal space. Resolution takes the
nearest declaration, so such a root is a project on every axis: it registers as
a project, its own repository holds its history, and it carries project
lifecycle behavior. Its position inside a personal space grants it nothing and

takes nothing from it. Whom it belongs to is a declared relationship, and
inside a home that declaration must name the home's owner
(`local/projects/teleclaude/spec/feature/config/project-ownership`). The acting
caller's identity is resolved independently of the enclosing person context.

## Canonical fields

### Use cases

#### UC-TIERP-1: Every declared tier answers all three questions

#### UC-TIERP-7: The global tier answers all three questions

#### UC-TIERP-2: A tier never inherits another tier's answers

#### UC-TIERP-3: Participation on one axis grants nothing on another

#### UC-TIERP-4: The person tier answers all three questions

#### UC-TIERP-5: A project inside a personal space is an ordinary project

#### UC-TIERP-6: A project in a personal space cannot name another owner

## Known caveats

- This contract states which tier is asked which question and what each tier
  answers. What a project's subscriptions mean, how they are declared, and what
  plumbing each one gates remain owned by
  `local/projects/teleclaude/spec/feature/config/project-capability-manifest.md`.
- Answering truthfully for a tier is not a grant. Any operation beyond what the
  tier model already establishes for the global, person, and company tiers
  requires its own product authority and is not conferred here.

## See Also

- docs/local/spec/feature/agent_runtime/sealed-commit.md — which invocations may commit and over what; a tier answer is an input to that contract, never a grant made here.
- ~/.teleclaude/docs/general/design/configuration-tiers.md — the tier model this contract composes with.
