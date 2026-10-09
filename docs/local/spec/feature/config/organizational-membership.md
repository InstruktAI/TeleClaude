---
description: How a person's company membership, company role, and project assignment
  are declared in the company's own configuration, validated against registered referents,
  and maintained through the ordinary operator surface.
---

# Organizational Membership Declaration — Spec

## Required reads

- @docs/local/spec/domain/config.md

## What it is

Organizational membership is declared configuration: which companies a person
belongs to, the role held in each, and which projects that person is assigned
to. This spec owns the declaration itself — where it is stated, what makes it
valid, and the operator surface that writes it.

It does not own what those facts mean or what resolving them reports. That is
`local/projects/teleclaude/spec/feature/identity/organizational-membership`, which reads the
declarations this contract persists and reinterprets nothing. The crossing runs
one way: this contract publishes validated declarations, and the identity
contract resolves them.

The declarations are carried by the company's own configuration tier, alongside
the business they describe. An assignment therefore concerns a project that
company owns.

Assignment is not ownership. Which person or company owns a project is declared
on the project itself and owned by another contract; this one states only who
may work in a project, and never settles or implies whose project it is.

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

**Company role**

<!-- planned-change:help-desk-master-routing -->

: The role a person holds in the business, drawn from the person-role vocabulary the platform role also uses: `admin`, `member`, `contributor`, `newcomer`. `admin` is the company's own administrator and owner. Every membership declaration carries one; a declaration naming any other value is invalid.

<!-- change:help-desk-master-routing -->

: The role a person holds in the business, drawn from the person-role vocabulary the platform role also uses: `admin`, `member`. `admin` is the company's own administrator and owner. Every membership declaration carries one; a declaration naming any other value is invalid.

<!-- /planned-change:help-desk-master-routing -->

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

#### UC-CFG-MEMBER-11: An assignment to a company's project requires membership in that company

```gherkin
Given a registered company that owns a registered project
And a person who holds no membership in that company
And a human administrator operating the maintenance surface
When the administrator assigns that person to that project
Then the assignment is refused at the point it is written
And the refusal names the missing membership in the owning company
And no assignment is persisted for that person
And declaring the membership first and repeating the assignment succeeds
```

#### UC-CFG-MEMBER-12: Withdrawing a membership removes the assignments it carried

```gherkin
Given a person who belongs to a company and is assigned to one or more of that company's projects
And a human administrator operating the maintenance surface
When the administrator withdraws that membership
Then the membership declaration is removed together with every assignment it carried
And the response names the assignments that were removed with it
And the person's declarations in other companies are unchanged
```

#### UC-CFG-MEMBER-13: Removing a registered person removes their roster entries

```gherkin
Given a person registered on the platform who holds memberships in one or more companies
And a human administrator operating the person-management surface
When the administrator removes that person from the platform
Then every roster entry naming that person is removed, with the assignments each carried
And the response names each company whose roster changed
And no roster entry remains that references an unregistered person
```

## Known caveats

- Use-case identifiers 4 through 7, 9, and 10 are not in use in this contract
  and are not reused.
- Two inert organizational declarations sit in the configuration schema: a
  per-person company-membership list and a per-company owner reference. Neither
  has a resolver and neither is populated. This contract is the single home for
  the owner relationship; the owner reference is not a second one, and both
  legacy declarations are removed from the schema outright. Nothing is migrated; a file still carrying either key fails at load naming it.
- The membership prerequisite is relational: it binds an assignment to the
  company owning the project it names. It places no requirement on a person who
  belongs to no company, and imposes nothing on a platform where no company is
  registered — there, no declaration of either kind has a subject, and the
  person-to-role mapping such a platform relies on is the platform role, which
  this contract does not touch.
- A membership entry owns the assignments nested in it. Withdrawing the entry,
  or removing the person it names, removes those assignments with it rather than
  refusing until they are cleared one by one; the response names what went. A
  roster never retains an entry for a person who is no longer registered.
- Nothing here introduces a default or implicit company. A person who belongs to
  no company holds no membership declaration, rather than membership in a
  standing group.

## See Also

- docs/local/spec/feature/identity/organizational-membership.md — what these declarations mean and what resolving them reports.
- ~/.teleclaude/docs/general/design/configuration-tiers.md — the tier model these declarations live in, and the two failure modes this contract exists to prevent.
