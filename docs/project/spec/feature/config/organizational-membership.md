---
description: A person declares which companies they belong to, the role held in each, and which projects they are assigned to; membership and assignment are independent, and an agent resolves both from configuration alone.
delivered_by:
  - company-member-roster
---

# Organizational Membership — Spec

## What it is

Organizational membership is a person's declared relationship to the businesses
and projects of the platform. Two facts are declared for each person:

- **Company membership** — which companies this person belongs to, and the role
  held in each business.
- **Project assignment** — which projects this person is assigned to work in.

Belonging to a company confers no project assignment. The single exception is a
person holding a company's administrative role, whose membership covers every
project that company owns without a per-project entry naming each one.

These are declared facts and the answers resolution reports about them. Nothing
here permits or refuses an operation: a consumer that turns these facts into
permission owns that decision itself.

Organizational membership is independent of the platform role. The platform role
governs authority over TeleClaude itself and decides who may maintain a
membership declaration; it states nothing about any business. The company role
states one person's relationship to one business; it confers no platform
authority. Neither follows from the other.

The company role is an identity fact about a business relationship. It is not a
visibility tier: nothing here grades what a member may read by the role they
hold.

A person with no declaration holds no company relationship and no project
assignment. Absence resolves to nothing, never to a default company.

This spec owns the declaration, its validation, its maintenance surface, and the
resolution that answers both questions. What any consumer then does with the
answers — documentation visibility, command authorization, provisioning onto a
business system — is owned by that consumer.

## Canonical fields

### Ubiquitous language

**Company membership**
: A person's declared belonging to one registered company, carrying the role that person holds in that business.

**Company role**
: The role a person holds inside one business, drawn from the platform's declared company-role vocabulary. Independent of the platform role, and never a visibility tier.

**Project assignment**
: A person's declared assignment to work in one registered project. Authoritative on its own; never inferred from company membership.

**Company administrative role**
: The company role whose holder's membership covers every project that company owns, with no per-project entry. The sole place a company role affects what resolution reports.

**Undeclared person**
: A person carrying no company membership and no project assignment. Resolves to no company relationship and an empty assignment set.

### Use cases

#### UC-CFG-MEMBER-1: An administrator declares a person's company membership and role

```gherkin
Given a registered company and a person who holds no membership in it
And a human administrator operating the organizational-membership configuration surface
When the administrator declares that the person belongs to that company holding a stated company role
Then the declaration is accepted and persisted
And resolving that person reports the company among their memberships with the stated role
And no file was edited by hand to achieve it
```

#### UC-CFG-MEMBER-2: An administrator withdraws a person's company membership

```gherkin
Given a person who belongs to a registered company
And a human administrator operating the organizational-membership configuration surface
When the administrator withdraws that membership
Then the declaration is removed
And resolving that person no longer reports that company among their memberships
And the person's remaining memberships are unchanged
```

#### UC-CFG-MEMBER-3: An administrator declares a person's project assignments

```gherkin
Given a registered project and a person not assigned to it
And a human administrator operating the organizational-membership configuration surface
When the administrator assigns the person to that project
Then the assignment is accepted and persisted
And resolving that person reports the project among their assignments
And the administrator can later withdraw that assignment through the same surface
```

#### UC-CFG-MEMBER-4: An agent resolves both facts from configuration alone

```gherkin
Given a person who belongs to at least one company and is assigned to at least one project
When an agent session asks the platform for that person's organizational membership
Then it receives the companies that person belongs to and the role held in each
And it receives the projects that person is assigned to
And it obtains both without consulting a human and without reading any business system
```

#### UC-CFG-MEMBER-5: Company membership alone yields no project

```gherkin
Given a person who belongs to a company that owns at least one project
And the person holds a company role that is not the administrative one
And the person carries no project assignment
When an agent resolves that person's organizational membership
Then the company appears among their memberships
And their project assignments are empty
And the projects that company owns are not among them
```

#### UC-CFG-MEMBER-6: A company's administrative role covers that company's projects without per-project entries

```gherkin
Given a person who belongs to a company holding that company's administrative role
And the person carries no project assignment naming any of that company's projects
When an agent resolves that person's organizational membership
Then every project that company owns is reported as covered by that membership
And no other company's projects are reported as covered
```

#### UC-CFG-MEMBER-7: An undeclared person holds no company relationship

```gherkin
Given a person registered on the platform who carries no membership and no assignment declaration
When an agent resolves that person's organizational membership
Then their company memberships are empty
And their project assignments are empty
And no company is supplied as a default
```

#### UC-CFG-MEMBER-8: A declaration naming an unregistered company or project is refused

```gherkin
Scenario Outline: An unregistered referent is refused at write time
Given a human administrator operating the organizational-membership configuration surface
When the administrator declares a membership or assignment naming a <referent> that is not registered
Then the declaration is refused at the point it is written
And the refusal names the <referent> that could not be resolved
And nothing is persisted for that person

Examples:
  | referent |
  | company  |
  | project  |
```

#### UC-CFG-MEMBER-9: The platform role is unchanged by organizational membership

```gherkin
Given a person carrying a platform role
When an administrator declares, changes, or withdraws that person's company membership or project assignment
Then the person's platform role is unchanged
And every decision that reads the platform role behaves exactly as before
And holding any platform role confers no company membership and no project assignment
```

## Known caveats

- The company-role vocabulary is a closed set whose values are the business
  owner's to ratify. Until that ratification lands, scenarios here name the
  administrative role by its function rather than by a literal value.
- UC-CFG-MEMBER-6 is the only place a company role affects what resolution
  reports. Any further derivation from company role is a change to this
  contract, not an implementation detail.
- Which configuration file is authoritative for these declarations is an open
  product decision at the time of authoring. The contract above holds either
  way: it states the facts and the answers, and names no file.

## See Also

- docs/project/spec/feature/config/person-identity-schema.md — the person declaration this one sits beside; it owns identity and the platform role.
- ~/.teleclaude/docs/general/design/configuration-tiers.md — the tier model these declarations live in, and the two failure modes this contract exists to prevent.
