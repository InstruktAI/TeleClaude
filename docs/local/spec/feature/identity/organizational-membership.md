---
description: What a person's company membership, company role, and project assignment
  mean, and what resolving them reports — belonging to a company confers no project,
  and a company role is the person's role held at that company's scope.
---

# Organizational Membership — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/feature/config/organizational-membership.md

## What it is

Organizational membership is a person's relationship to the businesses and
projects of the platform, expressed as two facts:

- **Company membership** — which companies this person belongs to, and the role
  held in each business.
- **Project assignment** — which projects this person is assigned to work in.

This spec owns what those facts mean and what resolving them reports. The
file-backed declaration through which they are stated, validated, and maintained
is owned by `projects/teleclaude/spec/feature/config/organizational-membership`; resolution
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

A company role is a person role held at that company's scope. It is drawn from
the same vocabulary as the platform role and means the same thing; the scope
bounds what it reaches (`projects/teleclaude/design/architecture/scoped-roles`). Declaring,
changing, or withdrawing a membership never changes the person's platform role,
and holding a platform role confers no membership.

Resolution also answers a person's effective role for an object: the
highest-ranked role the person holds at any scope containing that object, and
`customer` where none does. Consumers read that answer and never re-derive it
from the facts above.

A person with no declaration holds no company relationship and no project
assignment. Absence resolves to nothing, never to a default company.

## Canonical fields

### Ubiquitous language

**Company membership**
: A person's belonging to one registered company, carrying the role that person holds in that business.

**Company role**
: The person role held at one company's scope, drawn from the one person-role vocabulary (`admin`, `member`, `contributor`, `newcomer`). `admin` is the company administrative role; the others reach only the company projects the person is assigned to.

**Project assignment**
: A person's assignment to work in one registered project. Never inferred from company membership.

**Company administrative role**
: `admin` — the company role whose holder's membership covers every project that company owns, with no per-project entry. The owner of that business.

**Effective role**
: The highest-ranked role a person holds at any scope containing a given object; `customer` where no scope contains it.

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
And holding any platform role confers no company membership and no project assignment
```

#### UC-ORGID-6: A person assigned to a company's project belongs to that company

```gherkin
Given a person carrying an assignment to a project owned by a company
When an agent resolves that person's organizational membership
Then that company appears among the person's memberships
And no resolved assignment names a project owned by a company the person does not belong to
```

#### UC-ORGID-7: Resolution on a platform carrying no companies reports nothing organizational

```gherkin
Given a platform on which no company is registered
And a person registered on that platform carrying a platform role
When an agent resolves that person's organizational membership
Then their company memberships are empty
And their project assignments are empty
And no company is supplied as a default
And the person's platform role is reported unchanged by this resolution
```

#### UC-ORGID-8: An assignment to a project the company no longer owns is not reported

```gherkin
Given a person assigned, in a company's roster, to a project that company owned when the assignment was recorded
And that project's own declaration now names a different owner, or none
When an agent resolves that person's organizational membership
Then that assignment is not among the person's reported assignments
And the person's membership in that company is reported unchanged
And the stale assignment is surfaced as stale rather than silently dropped, so an administrator can remove it
```

#### UC-ORGID-9: A company administrator's effective role inside the company's lineage is admin

```gherkin
Given a person holding no platform role who holds the administrative role in one company
When an agent resolves that person's effective role for that company, for a project that company owns, or for the platform's shared documentation
Then the effective role is admin
And the person's effective role for a project owned by a different company is customer
```

#### UC-ORGID-10: A role below admin reaches only assigned projects

```gherkin
Given a person holding no platform role who holds the member role in one company and is assigned to one of its projects
When an agent resolves that person's effective role for that project and for another project the company owns
Then the effective role for the assigned project is member
And the effective role for the unassigned project is customer
And the effective role for the company itself is member
```

#### UC-ORGID-11: The highest role across containing scopes applies

```gherkin
Given a person holding the member platform role and the administrative role in one company
When an agent resolves that person's effective role for a project that company owns
Then the effective role is admin
And the person's effective role for a project owned by no company is member
```

## Known caveats

- Coverage (UC-ORGID-3) and the effective role (UC-ORGID-9 to UC-ORGID-11) are
  the only answers derived from a company role. Any further derivation is a
  change to this contract, not an implementation detail.
- The two directions are not symmetric, and both are settled. Membership confers
  no project assignment; an assignment to a company-owned project presupposes
  membership in that company. The prerequisite binds an assignment to the
  company owning the project it names, so it says nothing about a person who
  belongs to no company.
- A project's owner is its own declaration and can change after an assignment
  names it. Resolution reads ownership at the moment of the question, so an
  assignment to a project the company no longer owns is inert — never reported
  as access, never fatal to loading the company's configuration, and visible as
  stale until an administrator removes it.
- Resolution reports the same shape on a platform carrying no companies as it
  does for an undeclared person: empty, never a default. On such a platform the
  effective role is the platform role, or `customer` where none is declared.

## See Also

- docs/local/spec/feature/config/organizational-membership.md — the declaration, validation, and maintenance surface these facts are stated through.
- docs/local/spec/feature/config/person-identity-schema.md — the person declaration carrying the platform role.
- docs/local/design/architecture/scoped-roles.md — the scopes, what each contains, and how an effective role is resolved.
