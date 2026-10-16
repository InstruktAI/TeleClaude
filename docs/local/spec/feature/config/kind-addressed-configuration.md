---
description: One kind-addressed CLI contract for initializing, listing, reading, and
  patching configuration subjects.
---

# Kind Addressed Configuration — Spec

## What it is

`telec config <kind> list|get|patch`, with `init` for every kind but `project`,
is the agent-facing resource surface for configuration. The singular kind is `computer`, `global`, `person`,
`company`, or `project`; an overlay subject's kind matches its declared
`kind`. `computer` identifies the machine configuration by its fixed location
in the machine home and does not become an overlay tier or a context root.
`computer` and `global` are singletons. A person, company, or project is
addressed by its stable slug, except where a project comes into being:
creation addresses the folder it makes, and adoption addresses the checkout the
caller stands in — the owning checkout of the repository that holds the caller's
current directory, or that directory itself when no repository holds it or when
the repository holding it is the global home's.

A project has two verbs of its own besides the resource operations:

- `create <name>` makes a new, empty project in the caller's own home's
  `projects/<name>`, owned by the caller. `create <name> --company <slug>` makes
  it in that company's `projects/<name>`, owned by the company.
  `create <name> --path <dir>` makes an ownerless platform project at a folder
  outside every home; it never combines with `--company`. The name is the
  project's slug: an invalid or already held name is refused before anything is
  written. The project gets its own repository on `main`, declares its owner,
  declares no capabilities yet, and is registered.
- `adopt` registers the folder the caller stands in, in place, as
  `local/projects/teleclaude/spec/feature/config/project-registry` describes.

Creating and adopting a project write nothing outside the project and the
project registry.

The operation names describe the result, regardless of the subject's storage
shape. For computer, global, person and company, `init` creates missing declarations and scaffolding and converges an
existing instance to the current required structure while preserving values
already set. It starts no agent and sends no invitation. Analysis is invoked
through an activatable procedure in an explicitly started session; an
invitation is a separate explicit action.

For a person or a company, `init` also scaffolds that home from the platform's
templates
(`local/projects/teleclaude/spec/feature/reconciliation/home-template-materialization`).
A person or company home receives its kind's `AGENTS.master.md` and its local
baseline manifests, and adopting a project that subscribes `docs` gives it its
local baseline manifests. A master and a baseline are each written only while
absent; an existing one stays as its home keeps it. No documentation taxonomy
directory is created.

Whether a `global`, `company`, or `project` home keeps a help desk is a field of
that home's declaration, and a `patch` of the declaration turns it on or off
under the same clearance as every other field of it. A person has no help desk.
Seeding writes a desk's master only while it is absent; an existing master is
its home's own source, recorded by the home's history and never rewritten.

A company help desk is seeded from the company help-desk template in the
company home's `help-desk/` by that company's `init` and by the platform home's
configuration-aware convergence at commit-boundary maintenance and through
`telec sync`, while its declaration enables it. Machine
installation seeds no desk
(`local/projects/teleclaude/spec/feature/reconciliation/home-template-materialization`).

For a project, the project's own convergence seeds the help desk in the
project's `help-desk/` at commit-boundary maintenance and through `telec sync`
whenever the project's declaration enables it
(`local/projects/teleclaude/spec/feature/reconciliation/project-plumbing-convergence`).

A project's declaration that enables its help desk also requires
`agents.enabled: true` on that project. The requirement is declared once on the
project's help-desk field through the field relationship of
`local/projects/teleclaude/spec/teleclaude-config` (Tier declaration and editor
schemas), so the editor flags a violating declaration and every configuration
write refuses it, naming the field to set. A global or company home declares no
capability blocks and carries no such requirement.

A help desk's master never requires its home's local documentation
(`general/policy/agent-artifact-governance`).

`list` enumerates registered instances; for a singleton it reports that one
subject. `get` returns the subject's effective view and an opaque revision for
a subsequent write. In the effective view each environment reference is resolved
from the environment its configuration surface owns
(`local/projects/teleclaude/spec/feature/config/yaml-env-var-expansion`): a
reference with no value there leaves its field out, and a substituted value
carries the meaning its declared field type gives it. Every set value of a field
the schema declares sensitive renders as the one configuration mask; every other
value renders as resolved. The stored documents keep their references, and the
revision identifies them. A patch built from a `get` view leaves each field that
still carries the mask as stored. A person view joins the identity entry in global
configuration with that person's overlay. It also reports the person's roles as
a marked read-only projection: one entry for each scope the person holds a role
at — the platform, or a company by name — with the role held there. An entry
below `admin` in a company also lists the projects the person is assigned to
there; an `admin` entry lists none, since it reaches every project that company
owns. Those facts remain sourced only from the person registry and company
rosters, and the projection authorizes nothing
(`local/projects/teleclaude/design/architecture/scoped-roles`).

A view also reports, as a marked read-only projection, every field whose stored
value is an environment reference: the field's path, the variable the reference
names, the environment that owns that variable, and whether the variable has a
value on this computer. It never carries the value. A reference with no value
appears in this projection although the effective view leaves its field out, so
an editor can tell a field that is unset from one that waits on a missing
variable.

`patch` targets one kind and instance. Mapping keys merge into the latest
document and an array supplied by the caller replaces that array in full.
Omitted fields remain unchanged. Removing a field, roster entry, or person
instance is an explicit patch intent, never inferred from omission. A person
removal also clears that person's company roster entries and reports the
affected companies and assignments. A patch supplies the revision obtained by
reading the subject immediately before writing; a stale revision is refused.
The config owner validates the complete candidate and writes under its file
transaction. A rejected patch changes none of its target's committed state.

Removing a field from the machine configuration also removes every mapping the
removal leaves empty, so that document never keeps an empty section that only a
removal produced.

A person patch addresses each top-level field to the document that declares it:
a field the identity entry declares changes the identity entry, also where the
overlay declares the same field, and every other field changes the overlay. The
`overlay` key carries a patch addressed to the overlay alone, which reaches every
overlay field, including those the identity entry also declares. Its value is a
mapping, and the overlay's validation refuses a field the overlay does not
declare. A patch that names the same overlay field both at the top level and
under `overlay` is refused. Neither form writes `slug` or a read-only
projection.

Company membership, company role, and project assignments are patched only
through the company subject. A company roster entry names a registered person;
an assigned project is registered and owned by that company. Membership is a
prerequisite for an assignment. Company administrators cover company-owned
projects by role, without explicit project entries. The platform role on the
person entry remains independent of the company role.

The command boundary passes the verified caller, target instance, and affected
fields to identity-owned clearance before mutation, and clearance decides who
may perform that operation on that subject
(`local/projects/teleclaude/spec/feature/identity/configuration-target-clearance`). An
agent's system role can narrow the caller's reach but cannot widen it.

The unqualified `telec config get|patch` routes and the old person CRUD routes
are absent. They never silently resolve to a new target. Operations outside
resource CRUD, including validation, the interactive wizard, environment
management, and service actions, remain explicit operational surfaces and do
not change a kind or instance by implication.

## Canonical fields

### Shared configuration editor

Configuration editing has one daemon-owned contract, consumed by terminal and
web clients. UI clients address the API, whose adapter constructs the internal
configuration command; the CLI constructs the same internal command for daemon
submission. The addressed daemon executes the command through the configuration
owner under the caller's configuration target clearance. Command transport does
not execute configuration operations in the client process
(`sdlc/principle/architecture-boundary-purity`,
`sdlc/policy/domain-ownership`).

Wire request and answer types load independently of operation handlers and
runtime bootstrap. The CLI loads the request contract, identity and transport
it needs; operation handlers remain loaded in the daemon. Internal setup callers
continue to invoke the configuration owner's operations where installation runs
before the daemon is available. The daemon's ordinary command path does not
introduce another transport or an offline client execution path
(`sdlc/principle/module-depth`).

The editor read returns the subject revision, schema-derived field identities
and input metadata, and each field's effective display value. Resolution,
defaults, applicability, sensitivity masking, and the distinction between absent
and present values belong to the configuration owner. False, zero, and empty
collections retain their declared values. A configured sensitive value reaches
the client as the configuration mask; an absent value is explicitly absent.
Clients render the supplied values and use the supplied input metadata without
reconstructing configuration models or consulting environment state. The same
read contract serves every UI client.

An editor write names its subject, the field identity returned by the read,
the revision, and the user's keep, replace, or clear intent with the entered
value. The configuration owner converts submitted input through the declared
type, determines the owning source, validates the candidate, and performs its
targeted mutation. A whole-value environment reference retains its declaration:
replacement and clearing address the variable it actually names in its owning
environment, including a reference with a default. A literal remains owned by
its configuration document. Default elision and creation of a partial nested
structure are configuration-owned behavior. Omitted edits and keep leave state
unchanged; clearing is explicit. The write answers with the resulting masked
editor view or a structured failure.

An unchanged effective value leaves its declaration and environment untouched.
An embedded reference retains the existing owner contract for an effective edit
that cannot be represented as a targeted environment change
(`local/projects/teleclaude/spec/feature/config/yaml-env-var-expansion`).

Revision checking covers the state the field edit can change, including
environment-backed values, so a stale editor cannot overwrite a newer edit.
Validation precedes persistence, unchanged fields and unrelated environment
entries remain unchanged, and a rejected edit leaves committed state unchanged
(`local/projects/teleclaude/spec/feature/config/machine-config-write`).

The document-level `get` and merge-patch contracts remain distinct from field
editing: explicitly changing a stored reference is a document mutation, while
editing its effective value changes the referenced value. Both execute through
the same daemon-owned configuration commands. This contract supplies the shared
capability to web clients; it does not define a web-console screen.

### Read paths

Dotted paths passed to `get` address the selected configuration document. The
kind or instance in the command establishes the subject; a response envelope
adds no field-path segment. A person subject retains its identity and settings
sections. Selection retains
the response envelope and revision. Existing envelope-prefixed paths remain
accepted when no document-relative field resolves, with document-relative
paths taking precedence.

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

#### UC-KAC9: A person may change all of their own configuration

```gherkin
Given a person directs an agent acting under their verified identity
When that agent patches the person's own configuration, their registry identity fields included
Then the change is allowed if the agent's system role permits the operation
But a patch to another person's configuration or a company roster is refused without the authority required for that target
```

#### UC-KAC10: Machine configuration is explicit without joining overlay resolution

```gherkin
Given a machine configuration exists in the machine home
When an agent addresses computer configuration through the kind-based CLI
Then the machine configuration the runtime loads is selected
And the working directory selects no alternate machine file
And overlay-tier resolution still recognizes only the overlay kinds
```

#### UC-KAC11: Project adoption adopts the checkout the caller stands in

```gherkin
Given an agent standing in a subdirectory, or in a slug worktree, of a project's repository
When it adopts the project
Then the declaration, plumbing, and registration are those of the repository's owning checkout
And no declaration or plumbing is written into the subdirectory or the worktree
```

#### UC-KAC12: Initializing a person or company scaffolds its home

```gherkin
Given a person or company that has no home folder yet
When an administrator initializes it
Then its home holds its kind's AGENTS.master.md and the local baseline manifests
And no documentation taxonomy directory is created
And no help desk folder is created
```

#### UC-KAC13: Initializing again keeps the master and the baselines

```gherkin
Given a person or company home whose AGENTS.master.md differs from its kind's template
And whose local baseline manifests carry edits its owner made
When an agent initializes that subject again
Then the master keeps its content byte for byte
And each local baseline manifest keeps its content byte for byte
```

#### UC-KAC14: A company help desk follows the company's declaration

```gherkin
Given a company whose declaration does not enable a help desk
When an agent cleared to patch that company turns its help desk on through a patch of the declaration
Then the company declaration records its help desk as enabled
And values already set in the declaration are preserved
And after the company home next converges it holds a help-desk folder whose master is the rendering of the company help-desk template
And that master requires none of the company's local documentation
```

#### UC-KAC15:

#### UC-KAC16: Enabling a help desk requires administrator authority

### Cross-context references

- The config context owns kind resolution, initialization, validated mutation,
  and persistence. The identity context owns caller and target clearance.
- `local/projects/teleclaude/spec/feature/config/organizational-membership` owns roster
  validity; this surface changes how an administrator reaches that declaration.
- `local/projects/teleclaude/spec/feature/identity/organizational-membership` owns the meaning of
  membership and assignment, which this surface reports without reinterpreting.
- `local/projects/teleclaude/spec/feature/config/machine-config-write` owns the machine file's
  transaction and validation guarantee.
- The reconciliation context owns the template layers and what each target
  keeps across runs
  (`local/projects/teleclaude/spec/feature/reconciliation/home-template-materialization`,
  `local/projects/teleclaude/spec/feature/reconciliation/template-installation`);
  `init` applies them to the addressed home.

#### UC-KAC17: Creating a project makes an empty, owned, registered project

```gherkin
Given a person with no project named "budget" on this computer
When an agent acting for that person creates a project named "budget"
Then an empty project exists in that person's projects area with its own repository on main
And it is registered as "budget", owned by that person, with no capabilities declared
And creating "budget" again is refused before anything is written, saying the name is taken
```

#### UC-KAC18: A platform project is created at a path outside every home

```gherkin
Given a platform administrator
When an agent acting for them creates a project with a path outside every home
Then an ownerless project exists at that path, registered under its name
And the same request naming a company, or a path inside a home, is refused before anything is written
```

#### UC-KAC19: `get` shows the effective view with only sensitive values masked

```gherkin
Given a subject's configuration holds a field that references an environment variable with a value in the owning environment
And a field the schema declares sensitive holds a value
When an agent reads the subject with `get`
Then the referencing field shows the resolved value with its declared type
And the sensitive field shows the configuration mask instead of its value
And the stored document still holds the reference
```

#### UC-KAC20: A patch carrying the mask leaves the stored secret unchanged

```gherkin
Given an agent edits the output of `get` and submits it as a patch
And a sensitive field still carries the configuration mask
When the patch is applied
Then that sensitive field keeps its stored value
```

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

- docs/local/adr/0099-address-configuration-by-kind.md
