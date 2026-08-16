---
id: project/spec/feature/workflow/domain-ownership-enforcement
type: spec
domain: project
scope: project
description: Preparation and review keep every domain rule in one bounded-context owner, independently verify its layer placement, and refuse scope or policy leakage into consumers.
---

# Domain Ownership Enforcement — Spec

## What it is

Software-delivery workflow preserves bounded-context ownership from intent
through review. Every changed behavior, invariant, state transition, validation
rule, and vocabulary decision resolves to one context owner and one
architectural layer inside that owner. Cross-context work composes published
contracts; it does not move or duplicate participating policy. Hosting,
proximity, existing placement, todo atomicity, and adjacent pattern consistency
never establish ownership.

## Canonical fields

### Use cases

#### UC-WDOE-1: A plan identifies owner and layer independently

```gherkin
Given an agent prepares work that changes a domain rule
When the implementation plan is reviewed
Then the plan names the single bounded context that owns the rule
And the plan names the architectural layer used inside that context
And every cross-context consumer uses an explicit published contract
And correct layer placement does not excuse placement in a different context
```

#### UC-WDOE-2: Wrong-owner implementation is refused despite local consistency

```gherkin
Given an agent reviews a change that implements a domain rule outside its owning context
When the changed code matches the surrounding module's patterns or runs in the expected technical layer
Then the review reports the wrong-context placement as Critical
And the review does not treat current placement or adjacent consistency as ownership evidence
And the change is not approved until the rule is implemented by its owner and consumers use the owner's contract
```

#### UC-WDOE-3: Adjacent deficiencies remain separately owned

```gherkin
Given an agent discovers that an adjacent context's capability may be insufficient for the current outcome
When the current work has no authorization to redraw that context boundary
Then the current context continues to consume the adjacent context's existing contract
And any required adjacent change is recorded as a dependency or separately scoped proposal
And a reviewer finding does not authorize the current work to absorb or duplicate the adjacent context's behavior
```
