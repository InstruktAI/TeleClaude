---
description: Single bounded-context ownership for every domain decision, behavior, invariant, state model, and vocabulary term, composed with layer placement and explicit cross-context contracts.
---

# Domain Ownership — Policy

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md

## Rules

### Every domain rule has one owner

Every domain decision, behavior, invariant, state model, and vocabulary term has
exactly one bounded-context owner. The owner is the context whose domain meaning
and reason to change the rule expresses. Entry point, caller, adapter, scheduler,
runtime host, storage technology, todo boundary, file proximity, and existing
placement do not establish ownership.

The owner defines the rule once behind its published contract. Consumers may
invoke, translate, observe, or cache that contract while preserving its source
of truth. They never restate, specialize, validate, default, or recover the
owner's rule in a way that creates a second decision point.

### Domain ownership and layer placement are independent coordinates

Every implementation has both:

- one bounded-context owner, which answers **whose rule is this?**; and
- one architectural layer, which answers **how does that owner expose or execute it?**

Correct placement on one coordinate never compensates for the other. Code in a
core or handler layer is still misplaced when it implements another context's
rule. Code inside the owning context is still misplaced when domain policy is
implemented in its adapter or infrastructure layer.

### Boundaries compose; they do not blur

A work item may coordinate changes across multiple contexts, but every change
remains local to its owner. Cross-context interaction uses the owners' explicit
commands, queries, events, or published types. A coordinating flow and a
cross-cutting design document own the relationship between those contracts;
they own none of the participating domain behavior.

Discovering that an adjacent capability may be insufficient does not make that
capability part of the current owner. The current work consumes its existing
contract. A required change is separately scoped to that capability, or the
context boundary is deliberately redrawn in the context map and both affected
domain specs before implementation. Authorization may approve that re-scoping;
it never turns ownership leakage into a valid design.

### Hosting and reuse confer no authority

Deployment units, daemon workers, shared infrastructure, utility modules, and
framework extension points own mechanics only. Hosting a behavior does not make
the host its domain owner. Likewise, adjacent code and established patterns are
evidence about current implementation, never authority to repeat a wrong-owner
placement.

When no single owner can be named, the architecture is unresolved. Implementation
does not begin until the contexts, relationship, and public contract are explicit.

## Rationale

Layering, dependency inversion, and narrow interfaces can all be satisfied while
behavior still lives in the wrong bounded context. That failure is durable: the
consumer becomes a second policy owner, later changes diverge, and a convenient
technical host turns into a domain grab bag. Requiring one semantic owner and one
layer placement keeps decisions local while allowing cross-context workflows to
compose them freely.

## Scope

Applies to all production behavior, durable state, domain contracts, feature and
domain specs, architecture, plans, and reviews in software-development work.

## Enforcement

- Architecture identifies the bounded-context owner and layer placement of every
  changed behavior, invariant, and state model, plus the contract used at each
  crossing.
- Plans keep cross-context changes partitioned by owner and reference the owning
  domain spec for each task.
- Builders stop and return a plan or architecture that places a rule outside its
  owner; they do not implement it and defer the cleanup.
- Review treats a duplicated domain decision, direct access around an owner's
  contract, or behavior implemented in the wrong context as Critical.
- Types, package visibility, import rules, and storage APIs enforce boundaries
  mechanically where they can. Semantic ownership remains reviewer judgment; no
  prose scanner or path-name heuristic decides it.

## Exceptions

None. A context boundary may be deliberately redrawn, but that is a change to the
ownership contract, not an exception to it.
