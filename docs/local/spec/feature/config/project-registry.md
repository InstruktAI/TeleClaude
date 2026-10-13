---
description: The machine's one list of the places agent sessions work — adopted project roots and person or company homes — who writes it, what each entry is, and which consumers read which entries.
visibility: internal
---

# Project Registry — Spec

## What it is

The project registry is the machine's one list of the places agent sessions
work. No other list of projects exists on a machine. Its shape and location are
config's, stated in `local/projects/teleclaude/spec/teleclaude-config`.

Every entry is an adopted folder whose own configuration declares what it is. A
folder declaring the project tier is a project. A folder declaring the person or
company tier is a session home: sessions run there, but it is not a project.
Consumers that act on projects — documentation publisher resolution, the
valid-domain set, global skill composition, configuration migration, git
plumbing convergence, the project catalog, the removed-todo retention sweep, and
bug filing — enumerate project entries only. Consumers that place sessions — the
daemon's project listing that TUIs and the API show, mapping a session's working
directory onto its project, and the Discord project forums — enumerate every
entry.

<!-- planned-change:release-development-checkouts -->

An entry's identity is its slug: a project's own project slug, which
initialization derives from the folder name, or a home's tier slug. A project's
display name is its declared project name, then its slug. A person home's
display name is its declared home name, then the global person name, then its
slug. A company home's display name is its declared name, then its slug. Each
entry's description comes from its own configuration when present. Identities
are unique among a machine's entries.
<!-- change:release-development-checkouts -->

A logical project's identity is its declared slug. The registry can associate
an installed checkout and its development checkout with that identity,
distinguishing each location's purpose and retaining one primary workflow-state
location. The cloned source declaration is unchanged; machine-local checkout
purpose does not rename the project. An unrelated folder claiming an existing
identity remains a conflict. The config-owned registry model owns the serialized
association and its validation.

Session placement exposes both locations with their checkout purpose.
Project-wide consumers enumerate the logical project once: jobs, bug intake,
retention, lifecycle dispatch and publisher ownership do not multiply with its
checkouts. An existing logical-project address retains its primary identity;
an explicit checkout selection resolves only a member of that association.
Workflow owns purpose-specific root resolution
(`local/projects/teleclaude/design/architecture/command-scope`).
<!-- /planned-change:release-development-checkouts -->

<!-- planned-change:release-development-checkouts -->

Creation and adoption are what write the registry, and nothing else does: no
deployment or synchronization path adds, removes, or rewrites an entry.
Creation is reached through `telec config project create`, which makes a new
project and records it. Adoption is reached through `telec config project
adopt`, through the daemon's add-project request that TUIs send, and through
the configuration migration that retires the machine configuration's former
trusted-directory list. Adopting a folder that declares the person or company
tier records it as it is. Any other folder is set up as a project first, as
`general/procedure/project-initialization` describes, and a folder that
declares no tier becomes a project. A folder declaring the global tier is
refused, and so is a folder whose identity another entry already holds.
Recording is idempotent, so adopting an already-recorded folder changes
nothing beyond converging it.

A project created inside a person's or a company's home lands directly in that
home's `projects/` folder. Adoption keeps a project where it already is,
anywhere the caller can reach, inside a home or not. Either way a project inside
a home is its own repository: the global home's repository never holds a
project.

The recorded path is always the durable main checkout. A project may be adopted
from inside a linked worktree, and the registry still names the checkout that
owns it, so an ephemeral worktree path is never enumerated as a project.
<!-- change:release-development-checkouts -->

Creation and adoption own registry writes. Installation provisioning calls
the adoption owner's checkout-association operation to register its companion
atomically with the existing logical project. It neither appends an unrelated
duplicate project nor writes the backing file itself. Retry preserves the same
association. Ordinary publication and synchronization do not adopt folders.

Person and company homes retain their existing tier identities and session
placement behavior. Project creation/adoption retains its owner and declaration
contracts. A linked worktree is represented by its owning registered checkout,
never as another project entry. The association's durable locations survive
changes of channel and repeated installation.

The original registered location retains existing workflow state. Migration
resolves an association before any consumer can create another store or take a
second project-wide responsibility. Existing worktrees and claims retain their
owner until a coordinated transition has preserved their work
(`general/principle/trust-and-guardrails`).
<!-- /planned-change:release-development-checkouts -->

### The retired trusted-directory list

A machine configuration that still lists trusted directories has that list
folded into the registry by a configuration migration, on every machine that
carries one. The migration adopts each listed folder that exists, in list order,
after the entries the registry already holds. It carries each entry's name and
description into the adopted folder's tier configuration where the corresponding
field is absent. The Discord reflection hand-off binds each former-name key to
the folder that received threads from that forum before the fold. When several
entries shared one former name, every present folder is adopted, but only that
prior routing owner inherits the existing forum; the other entries receive
separate identity-keyed forums (`local/projects/teleclaude/spec/feature/integration/discord-admin-reflection-state`). A listed
folder that no longer exists is dropped and named in the migration run's
structured record. A listed folder whose
identity another entry already holds is a conflict: the machine configuration
keeps its list and its version, and the run reports the conflict.

Until the machine configuration is stored past that migration, the consumers
that place sessions also see the folders the list still holds
(`local/projects/teleclaude/policy/configuration-migrations`); a folder not yet adopted is not a
project to the project-acting consumers.

## Canonical fields

<!-- planned-change:release-development-checkouts -->

- **Entry.** One adopted folder, addressed by its durable main checkout.
- **Kind.** The tier the folder's own configuration declares: project, person,
  or company.
- **Identity.** The entry's slug, unique among the machine's entries.
- **Display name.** The entry's declared tier-local name, then the global person
  name for a person home, then the slug.
- **Order.** Entries keep the order in which they were adopted. Consumers that
  present entries follow it.

- **Writer.** Creation and adoption only. Idempotent, and never performed by a
  deployment or synchronization path.

- **Readers.** Project-acting consumers read project entries; session-placing
  consumers read every entry. None discovers projects from the filesystem or
  from any other list.

<!-- change:release-development-checkouts -->

- **Logical entry.** A registered project or person/company session home,
  retaining its unique logical identity and existing declaration/display name.
- **Checkout association.** A project's registered installed and development
  locations, their distinct purposes and its one primary workflow-state root.
  A checkout selection is scoped to that logical entry.
- **Order.** Logical entries retain adoption order; associated physical
  locations remain distinguishable in session placement.
- **Writer.** Config's creation/adoption operations, including installation's
  idempotent request to associate its companion. Publication performs no registry
  write.
- **Readers.** Project-wide consumers enumerate logical projects once. Session
  placement also exposes their associated checkout locations. The registry is
  the sole source of those relationships.

<!-- /planned-change:release-development-checkouts -->

### Use cases

#### UC-CFG-REG1: Adoption records a project's durable main checkout

```gherkin
Given a project whose linked worktree is checked out alongside its main checkout
When an agent adopts that project from inside the worktree
Then the registry lists the project once, by its main checkout
And the worktree is absent from the registry
And adopting it again leaves the registry unchanged
```

#### UC-CFG-REG2: Publication never writes the registry

```gherkin
Given a project that is not recorded in the registry
And that project publishes a documentation domain
When recorded-commit maintenance publishes that project's committed source
Then the registry still does not list that project
And publication completes its own phases
```

#### UC-CFG-REG3: The retired trusted-directory list folds into the registry

```gherkin
Given a machine configuration that lists trusted directories, each with a name and a description
And one listed folder holds neither a git repository nor a TeleClaude configuration
When a migration run reaches that machine configuration
Then the registry lists every listed folder that exists, in list order after the entries it already held
And the folder that held nothing is a project whose repository is on main
And each adopted folder's tier configuration carries its listed name and description where the corresponding field was absent
And an agent reading the machine configuration finds no trusted-directory list
```

#### UC-CFG-REG4: A listed folder that no longer exists is dropped and reported

```gherkin
Given a machine configuration that lists a trusted directory whose folder no longer exists
When a migration run reaches that machine configuration
Then the registry does not list that folder
And an agent reading the migration run's structured records finds the dropped folder named
```

#### UC-CFG-REG5: An identity collision keeps the trusted-directory list in place

```gherkin
Given a machine configuration that lists a folder whose identity another registry entry already holds
When a migration run reaches that machine configuration
Then the machine configuration keeps its trusted-directory list and its version
And an agent reading the migration run's structured records finds the conflict for that document
```

#### UC-CFG-REG6: A session home is listed but is not a project

```gherkin
Given a person home is on the registry
When an agent lists the projects on that machine through the daemon
Then the person home is among the listed entries
But documentation publication, plumbing convergence, and project configuration migration do not treat it as a project
```

#### UC-CFG-REG7: A folder still waiting in the trusted-directory list stays visible

```gherkin
Given a machine configuration that still lists a trusted directory that is not yet on the registry
And no migration run or writer has yet stored that configuration past the fold
When an agent lists the projects on that machine through the daemon
Then that folder is among the listed entries
And the machine configuration and the registry are unchanged by the listing
```

#### UC-CFG-REG8: Adoption refuses a folder whose identity another entry holds

<!-- planned-change:release-development-checkouts -->

```gherkin
Given the registry holds an entry with a given identity
When an operator or agent adopts a different folder that derives the same identity
Then the adoption is refused, naming the entry that holds the identity
And the registry is unchanged
```

<!-- change:release-development-checkouts -->

```gherkin
Given the registry holds an entry with a given identity
When an operator or agent adopts an unrelated folder that derives the same identity
Then the adoption is refused, naming the entry that holds the identity
And the registry is unchanged
```

<!-- /planned-change:release-development-checkouts -->

#### UC-CFG-REG9: A home that is not on the registry holds no identity

```gherkin
Given a company home whose configuration exists on the machine but which is not on the registry
And a machine configuration that lists a project folder deriving the same identity as that home's slug
When a migration run reaches that machine configuration
Then the registry lists that project folder
And an agent reading the machine configuration finds no trusted-directory list
And the company home is still not on the registry
```

#### UC-CFG-REG10: Adopting a folder inside a home registers it as itself

```gherkin
Given a folder in a person's projects area that holds work but no repository of its own
When an operator or agent adopts that folder
Then the folder holds its own repository on main
And the registry lists that folder under its own identity, owned by that person
And the global home is not listed as a project
```

#### UC-CFG-REG11: Adoption inside a home keeps the project where it is

```gherkin
Given a folder holding work inside a person's home, outside that home's projects area
When that person adopts it
Then the project is registered at that folder, owned by that person
And no file is moved
```

#### UC-CFG-REG12:

<!-- planned:release-development-checkouts -->

#### UC-CFG-REG13: A development companion is another location of the same project

```gherkin
Given an operator's installation already has a registered project
When installation associates its development companion
Then the operator can select either checkout by its purpose
And project-wide work still has one logical project identity
And repeating the association creates no additional entry
```

#### UC-CFG-REG14: Unrelated duplicate identities remain conflicts

```gherkin
Given a registered project already holds an identity
When an agent attempts to register an unrelated checkout under that identity
Then registration reports the existing owner
And the existing association is unchanged
```

<!-- /planned:release-development-checkouts -->

## Known caveats

- A project cloned onto a machine and never adopted there is absent from the
  registry, so the consumers above do not enumerate it. Adoption is the act that
  makes a checkout a project on this machine.
- A trusted-directory folder that is only temporarily unreachable when the fold
  runs — an unmounted volume — is dropped like a deleted one. Adopting it again
  once it is reachable restores it.
