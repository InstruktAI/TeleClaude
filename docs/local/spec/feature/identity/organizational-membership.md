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
is owned by `local/projects/teleclaude/spec/feature/config/organizational-membership`; resolution
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
bounds what it reaches (`local/projects/teleclaude/design/architecture/scoped-roles`). Declaring,
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

: The person role held at one company's scope, drawn from the one person-role vocabulary (`admin`, `member`). `admin` is the company administrative role; `member` reaches only the company projects the person is assigned to.

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

#### UC-ORGID-2: Company membership alone yields no project

#### UC-ORGID-3: A company's administrative role covers that company's projects without per-project entries

Coverage and explicit assignment are separately reported facts. Resolution never
folds a role-derived coverage answer into the assignments a person was
explicitly given, so a consumer may read explicit assignments alone and receive
nothing derived from any company role.

#### UC-ORGID-4: An undeclared person holds no company relationship

#### UC-ORGID-5: The platform role is unchanged by organizational membership

#### UC-ORGID-6: A person assigned to a company's project belongs to that company

#### UC-ORGID-7: Resolution on a platform carrying no companies reports nothing organizational

#### UC-ORGID-8: An assignment to a project the company no longer owns is not reported

#### UC-ORGID-9: A company administrator's effective role inside the company's lineage is admin

#### UC-ORGID-10: A role below admin reaches only assigned projects

#### UC-ORGID-11: The highest role across containing scopes applies

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
