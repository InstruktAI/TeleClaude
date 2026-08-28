---
description: How a person's company membership, company role, and project assignment are declared in the company's own configuration, validated against registered referents, and maintained through the ordinary operator surface.
delivered_by:
  - company-member-roster
---

# Organizational Membership Declaration — Spec

## What it is

Organizational membership is declared configuration: which companies a person
belongs to, the role held in each, and which projects that person is assigned
to. This spec owns the declaration itself — where it is stated, what makes it
valid, and the operator surface that writes it.

It does not own what those facts mean or what resolving them reports. That is
`project/spec/feature/identity/organizational-membership`, which reads the
declarations this contract persists and reinterprets nothing. The crossing runs
one way: this contract publishes validated declarations, and the identity
contract resolves them.

The declarations are carried by the company's own configuration tier, alongside
the business they describe.

A declaration is refused rather than stored when it names a company or project
that is not registered. Refusing an invalid declaration at write time is this
contract's own validation; it is not a decision about what any consumer may do
with a valid one.

## Canonical fields

### Ubiquitous language

**Membership declaration**
: A stated belonging of one person to one registered company, carrying the role held in that business.

**Assignment declaration**
: A stated assignment of one person to one registered project.

**Registered referent**
: A company or project that exists in the platform's own registries. Every declaration names one; a declaration naming anything else is invalid.

**Maintenance surface**
: The ordinary administrator-facing configuration surface through which declarations are written and withdrawn, so no declaration requires editing a file by hand.

### Use cases

#### UC-CFG-MEMBER-1: An administrator declares a person's company membership and role

```gherkin
Given a registered company and a person who holds no membership in it
And a human administrator operating the maintenance surface
When the administrator declares that the person belongs to that company holding a stated company role
Then the declaration is accepted and persisted
And the stored declaration names that person, that company, and the stated role
And no file was edited by hand to achieve it
```

#### UC-CFG-MEMBER-2: An administrator withdraws a person's company membership

```gherkin
Given a person who belongs to a registered company
And a human administrator operating the maintenance surface
When the administrator withdraws that membership
Then the declaration is removed
And no stored declaration remains binding that person to that company
And the person's remaining membership declarations are unchanged
```

#### UC-CFG-MEMBER-3: An administrator declares a person's project assignments

```gherkin
Given a person who belongs to a company
And a registered project that company owns, to which the person is not assigned
And a human administrator operating the maintenance surface
When the administrator assigns the person to that project
Then the assignment declaration is accepted and persisted
And the administrator can later withdraw that assignment through the same surface
```

#### UC-CFG-MEMBER-8: A declaration naming an unregistered company or project is refused

```gherkin
Scenario Outline: An unregistered referent is refused at write time
Given a human administrator operating the maintenance surface
When the administrator declares a membership or assignment naming a <referent> that is not registered
Then the declaration is refused at the point it is written
And the refusal names the <referent> that could not be resolved
And nothing is persisted for that person

Examples:
  | referent |
  | company  |
  | project  |
```

## Known caveats

- Use-case identifiers 4 through 7 and 9 were assigned in an earlier revision of
  this contract and moved to
  `project/spec/feature/identity/organizational-membership` before either
  contract was delivered, because they state resolution meaning rather than
  declaration. They are not reused here.
- Two organizational declarations already exist in the configuration schema and
  are inert: a per-person company-membership list, and a per-company owner
  reference. Neither has a resolver and neither is populated. The owner
  reference states the same relationship a membership declaration carrying the
  administrative role states, so it is subsumed by this contract rather than
  kept as a second home for that fact.
- The company-role vocabulary is a closed set whose values are the business
  owner's to ratify.

## See Also

- docs/project/spec/feature/identity/organizational-membership.md — what these declarations mean and what resolving them reports.
- ~/.teleclaude/docs/general/design/configuration-tiers.md — the tier model these declarations live in, and the two failure modes this contract exists to prevent.
