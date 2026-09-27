---
description: One kind-addressed CLI contract for initializing, listing, reading, and
  patching configuration subjects.
---

# Kind Addressed Configuration — Spec

## What it is

`telec config <kind> init|list|get|patch` is the agent-facing resource surface
for configuration. The singular kind is `computer`, `global`, `person`,
`company`, or `project`; an overlay subject's kind matches its declared
`kind`. `computer` identifies the machine configuration by its fixed location
in the machine home and does not become an overlay tier or a context root.
<!-- planned-change:worktree-or-project-scope -->
`computer` and `global` are singletons. A person, company, or project is
addressed by its stable slug, except that project initialization
may establish the project rooted at the caller's current directory.
<!-- change:worktree-or-project-scope -->
`computer` and `global` are singletons. A person, company, or project is
addressed by its stable slug, except that project initialization addresses the
checkout the caller stands in: the owning checkout of the repository that holds
the caller's current directory, or that directory itself when no repository
holds it.
<!-- /planned-change:worktree-or-project-scope -->

The operation names describe the result, regardless of the subject's storage
shape. `init` creates missing declarations and scaffolding and converges an
existing instance to the current required structure while preserving values
already set. It starts no agent and sends no invitation. Analysis is invoked
through an activatable procedure in an explicitly started session; an
invitation is a separate explicit action.

`list` enumerates registered instances; for a singleton it reports that one
subject. `get` returns the current declared view and an opaque revision for a
<!-- planned-change:authorize-person-roles-at-scope -->
subsequent write. A person view joins the identity entry in global
configuration with that person's overlay. It also reports resolved company
memberships as a marked read-only projection; those facts remain sourced only
from company rosters.
<!-- change:authorize-person-roles-at-scope -->
subsequent write. A person view joins the identity entry in global
configuration with that person's overlay. It also reports the person's roles as
a marked read-only projection: one entry for each scope the person holds a role
at — the platform, or a company by name — with the role held there. An entry
below `admin` in a company also lists the projects the person is assigned to
there; an `admin` entry lists none, since it reaches every project that company
owns. Those facts remain sourced only from the person registry and company
rosters, and the projection authorizes nothing
(`project/design/architecture/scoped-roles`).
<!-- /planned-change:authorize-person-roles-at-scope -->

`patch` targets one kind and instance. Mapping keys merge into the latest
document and an array supplied by the caller replaces that array in full.
Omitted fields remain unchanged. Removing a field, roster entry, or person
instance is an explicit patch intent, never inferred from omission. A person
removal also clears that person's company roster entries and reports the
affected companies and assignments. A patch supplies the revision obtained by
reading the subject immediately before writing; a stale revision is refused.
The config owner validates the complete candidate and writes under its file
transaction. A rejected patch changes none of its target's committed state.

Company membership, company role, and project assignments are patched only
through the company subject. A company roster entry names a registered person;
an assigned project is registered and owned by that company. Membership is a
prerequisite for an assignment. Company administrators cover company-owned
projects by role, without explicit project entries. The platform role on the
person entry remains independent of the company role.

The command boundary passes the verified caller, target instance, and affected
fields to identity-owned clearance before mutation. A person may edit their
own settings through an agent acting under their authority. Registry identity
fields, platform role, company rosters, and machine or global settings retain
their respective administrator boundary. An agent's system role can narrow
the caller's reach but cannot widen it.

The unqualified `telec config get|patch` routes and the old person CRUD routes
are absent. They never silently resolve to a new target. Operations outside
resource CRUD, including validation, the interactive wizard, environment
management, and service actions, remain explicit operational surfaces and do
not change a kind or instance by implication.

## Canonical fields

### Use cases

#### UC-KAC1: An agent addresses every configuration subject by kind

```gherkin
Given configuration subjects of every kind exist
When an agent lists, reads, or changes one subject through the configuration CLI
Then the command names that kind and the subject's stable instance when needed
And an unqualified read or patch is refused without selecting a default subject
```

#### UC-KAC2: Initialization converges without side effects

```gherkin
Given a configuration subject exists with operator values already set
When an agent initializes that subject again
Then missing required structure is added
And existing values are preserved
And no agent session or invitation is started
```

#### UC-KAC3: A new person has one identity and one home

```gherkin
Given a registered person does not yet exist
When an administrator initializes that person
Then the person has one stable identity entry and one person overlay
And the command returns their stable slug
And the person has no implicit company membership or project assignment
And no invitation is sent
```

#### UC-KAC4: Company roster changes reach the company declaration

```gherkin
Given a registered person and company
When an administrator patches that company's roster with the person's role and project assignments
Then the company declaration records the accepted relationship
And no person declaration gains a second copy of it
And an unregistered or wrongly owned project is refused before persistence
```

#### UC-KAC5: A person read reports organizational facts without owning them

```gherkin
Given a person belongs to more than one company
When an authorized agent reads that person's configuration view
Then the view identifies their resolved memberships as read-only facts
And an attempt to patch those facts through the person subject is refused
```

#### UC-KAC6: A stale patch cannot discard another write

```gherkin
Given an agent read a configuration subject and obtained its revision
And another writer changed the same subject afterward
When the agent submits a patch based on the earlier revision
Then the patch is refused as stale
And the other writer's committed state remains unchanged
```

#### UC-KAC7: A patch replaces an array the caller supplies

```gherkin
Given a company roster entry contains project assignments
When an administrator reads the current entry and patches its projects array with a new complete array
Then that array replaces the earlier assignments
And unrelated mapping keys and roster entries remain unchanged
```

#### UC-KAC8: Removing a person clears their roster references

```gherkin
Given a registered person belongs to companies and has project assignments
When an administrator explicitly removes that person through the person resource
Then the person registration is removed
And every company roster entry naming them is removed with its assignments
And the result identifies the companies and assignments changed
```

#### UC-KAC9: A person may change their own settings without gaining registry authority

```gherkin
Given a person directs an agent acting under their verified identity
When that agent patches the person's own settings
Then the change is allowed if the agent's system role permits the operation
But a patch to the platform role, another person's settings, or a company roster is refused without the authority required for that target
```

#### UC-KAC10: Machine configuration is explicit without joining overlay resolution

```gherkin
Given a machine configuration exists in the machine home
When an agent addresses computer configuration through the kind-based CLI
Then the machine configuration the runtime loads is selected
And the working directory selects no alternate machine file
And overlay-tier resolution still recognizes only the overlay kinds
```

<!-- planned:worktree-or-project-scope -->
#### UC-KAC11: Project initialization adopts the checkout the caller stands in

```gherkin
Given an agent standing in a subdirectory, or in a slug worktree, of a project's repository
When it initializes the project configuration
Then the declaration, plumbing, and registration are those of the repository's owning checkout
And no declaration or plumbing is written into the subdirectory or the worktree
```
<!-- /planned:worktree-or-project-scope -->

### Cross-context references

- The config context owns kind resolution, initialization, validated mutation,
  and persistence. The identity context owns caller and target clearance.
- `project/spec/feature/config/organizational-membership` owns roster
  validity; this surface changes how an administrator reaches that declaration.
- `project/spec/feature/identity/organizational-membership` owns the meaning of
  membership and assignment, which this surface reports without reinterpreting.
- `project/spec/feature/config/machine-config-write` owns the machine file's
  transaction and validation guarantee.

## Known caveats

- `computer` has a different filename and runtime loader from the overlays.
  Its kind follows from its location, not from participation in overlay
  composition.
- A person view crosses the global registry, a person overlay, and company
  rosters. Only the declared fields of the addressed subject are writable;
  read-only projections grant no parallel write path.
- Project configuration remains in its owning repository. A CLI patch does not
  replace the repository's commit and review boundary.

## See Also

- docs/project/adr/0099-address-configuration-by-kind.md
