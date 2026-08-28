---
description: What a person's company membership, company role, and project assignment mean, and what resolving them reports — belonging to a company confers no project, and the platform role stays independent.
delivered_by:
  - company-member-roster
---

# Organizational Membership — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/feature/config/organizational-membership.md

## What it is

Organizational membership is a person's relationship to the businesses and
projects of the platform, expressed as two facts:

- **Company membership** — which companies this person belongs to, and the role
  held in each business.
- **Project assignment** — which projects this person is assigned to work in.

This spec owns what those facts mean and what resolving them reports. The
file-backed declaration through which they are stated, validated, and maintained
is owned by `project/spec/feature/config/organizational-membership`; resolution
reads the declared facts through that contract and reinterprets nothing.

Belonging to a company confers no project assignment. The single exception is a
person holding a company's administrative role, whose membership covers every
project that company owns without a per-project entry naming each one. Which
projects a company owns is read from each project's own declaration of its
owner; this contract never infers ownership from a project's location or from
anyone's assignment to it. Coverage reaches exactly the projects declaring that
company as owner, so a project owned by a person and a project owned by no one
are alike uncovered — a company role reaches neither.

Resolution reports facts. Nothing here grants or denies permission to a consumer
operation: a consumer that turns these facts into permission — documentation
visibility, command authorization, provisioning onto a business system — owns
that decision itself.

Organizational membership is independent of the platform role. The platform role
governs authority over TeleClaude itself and decides who may maintain a
membership declaration; it states nothing about any business. The company role
states one person's relationship to one business; it confers no platform
authority. Neither follows from the other.

The company role is not a visibility tier: nothing here grades what a member may
read by the role they hold.

A person with no declaration holds no company relationship and no project
assignment. Absence resolves to nothing, never to a default company.

## Canonical fields

### Ubiquitous language

**Company membership**
: A person's belonging to one registered company, carrying the role that person holds in that business.

**Company role**
: The role a person holds inside one business, one of `admin`, `member`, `contributor`. Independent of the platform role, and never a visibility tier.

**Project assignment**
: A person's assignment to work in one registered project. Never inferred from company membership.

**Company administrative role**
: `admin` — the company role whose holder's membership covers every project that company owns, with no per-project entry. The owner of that business. The sole place a company role affects what resolution reports.

**Undeclared person**
: A person carrying no company membership and no project assignment. Resolves to no company relationship and an empty assignment set.

### Use cases

#### UC-ORGID-1: An agent resolves both facts without asking a human

```gherkin
Given a person who belongs to at least one company and is assigned to at least one project
When an agent session asks the platform for that person's organizational membership
Then it receives the companies that person belongs to and the role held in each
And it receives the projects that person is assigned to
And it obtains both without consulting a human and without reading any business system
```

#### UC-ORGID-2: Company membership alone yields no project

```gherkin
Given a person who belongs to a company that owns at least one project
And the person holds a company role that is not the administrative one
And the person carries no project assignment
When an agent resolves that person's organizational membership
Then the company appears among their memberships
And their project assignments are empty
And the projects that company owns are not among them
```

#### UC-ORGID-3: A company's administrative role covers that company's projects without per-project entries

```gherkin
Given a person who belongs to a company holding that company's administrative role
And the person carries no project assignment naming any of that company's projects
When an agent resolves that person's organizational membership
Then every project declaring that company as its owner is reported as covered by that membership
And a project declaring a different owner is not reported as covered
And a project declaring no owner is not reported as covered
And their explicit project assignments remain empty
```

Coverage and explicit assignment are separately reported facts. Resolution never
folds a role-derived coverage answer into the assignments a person was
explicitly given, so a consumer may read explicit assignments alone and receive
nothing derived from any company role.

#### UC-ORGID-4: An undeclared person holds no company relationship

```gherkin
Given a person registered on the platform who carries no membership and no assignment declaration
When an agent resolves that person's organizational membership
Then their company memberships are empty
And their project assignments are empty
And no company is supplied as a default
```

#### UC-ORGID-5: The platform role is unchanged by organizational membership

```gherkin
Given a person carrying a platform role
When an administrator declares, changes, or withdraws that person's company membership or project assignment
Then the person's platform role is unchanged
And every decision that reads the platform role behaves exactly as before
And holding any platform role confers no company membership and no project assignment
```

## Known caveats

- Assignment is a narrowing inside a business, never a standing granted outside
  one.
- UC-ORGID-3 is the only place a company role affects what resolution reports.
  Any further derivation from company role is a change to this contract, not an
  implementation detail.
- The relation is asymmetric. Membership does not imply assignment: belonging to
  a company confers no project. Assignment does imply membership: an assignment
  requires membership in the company owning the project it names.

## See Also

- docs/project/spec/feature/config/organizational-membership.md — the declaration, validation, and maintenance surface these facts are stated through.
- docs/project/spec/feature/config/person-identity-schema.md — the person declaration carrying the independent platform role.
