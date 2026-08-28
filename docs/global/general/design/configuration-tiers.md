---
description: How TeleClaude finds its configuration files across the global, person, company, and project tiers, how those tiers relate to each other, and how that relationship governs what a caller may read.
---

# Configuration Tiers — Design

## Purpose

One filename, `teleclaude.yml`, carries configuration at every tier. This design
states where those files are, how each one is found, how the tiers relate to one
another, and what governs the portion of the documentation corpus a caller may
read.

## Inputs/Outputs

**Input — two discovery mechanisms, and no third.**

- **Projects self-register.** A project may live anywhere on disk, so it cannot
  be found by convention. Its root is recorded in the manifest at
  `~/.teleclaude/projects.yaml`, which stores roots only; each root's
  `teleclaude.yml` is then read to hydrate the project. Nothing walks the
  filesystem looking for projects.
- **Every other tier lives at a designated location.** The global configuration
  is `~/.teleclaude/teleclaude.yml`. A person is
  `~/.teleclaude/people/<slug>/teleclaude.yml`. A company is
  `~/.teleclaude/companies/<slug>/teleclaude.yml`. These need no registry
  because their location is a convention, not a discovery problem.

**Output — the tier set for an invocation**, the documentation sources it
implies, and the portion of those sources the caller may see.

## Invariants

- **Nothing scans for configuration.** Tiers are either registered or
  conventionally located. A design that adds a filesystem walk has misread the
  model.
- **Relationships are declared, not inferred from paths.** A project states its
  owning company in its own configuration, and that statement is what associates
  the two.
- **Persons and companies are not repositories of their own.** Their content
  belongs in the `~/.teleclaude` home repository; projects commit to theirs.
  Committing is independent of discovery — a commit works from any folder with a
  parent git configuration.
- **Platform role and company role are independent axes.** The platform role
  governs authority over TeleClaude itself; a company role states one person's
  relationship to one business. Neither follows from the other.
<!-- planned-change:docs-tier-layering -->
- **Today, authorization to read is one gate.** A caller resolves to a person
  and their platform role. An admin sees every snippet; everyone else sees only
  snippets declaring themselves public. There is no membership or ownership
  dimension in the read path — `PersonConfig.companies` is modelled and
  validated but has no consumer and no values on disk.
<!-- change:docs-tier-layering -->
- **Authorization to read is answered per tier.** A caller resolves to a person,
  their platform role, and their declared relationships. A tier the caller holds
  a relationship to is read in full; a tier they hold none to is read at whatever
  its snippets declare about themselves; a platform admin reads every tier in
  full.
<!-- /planned-change:docs-tier-layering -->
<!-- planned-change:config-kind-declaration -->
- **Today, invocation resolution is anchored on git.** Resolving the root for an
  invocation walks upward for a `.git` directory and only then requires
  `teleclaude.yml` beside it, so a folder holding a valid configuration with no
  repository above it fails. This is a defect of the current implementation, not
  a property of the model.
<!-- change:config-kind-declaration -->
<!-- /planned-change:config-kind-declaration -->

<!-- planned:config-kind-declaration -->
- **Meaning comes from the file, never from where it sits.** Each configuration
  file declares its own kind, and resolution reads that declaration. Location is
  how conventional tiers are found; it is never what makes them mean something.
- **Git has no part in finding TeleClaude configuration.** That a folder sits
  inside a repository, at any depth, is irrelevant to resolution. Git answers one
  separate question — where a project's shared state lives when a linked
  worktree is in play — and that question exists only for projects.
- **A company folder is a registry identity, not a root anything resolves
  against.** Standing inside one confers nothing: a company declaration
  terminates context resolution with no context root, and an invocation from
  within one behaves as an invocation with no context root.
<!-- /planned:config-kind-declaration -->

<!-- planned:docs-tier-layering -->
- **Belonging is binary for reading a company.** A company role carries business
  authority; it does not grade documentation access. Anyone with a declared
  relationship to a company — member, contributor, whatever the role — reads that
  company's documentation in full. There are no levels of allowance inside a
  company.
- **Company membership does not carry that company's projects.** Belonging opens
  the company's own documentation. What opens a project's documentation is the
  explicit declared assignment of a person to that project, and nothing else —
  including a company role broad enough to cover that company's projects for
  other purposes. Documentation reach consumes the assignment fact specifically,
  never a wider coverage answer computed from a role. Which declarations
  establish an assignment, and where they are declared, belong to the
  configuration tier; what documentation does with them belongs here.
- **A caller's scope is exactly three things.** Their own person tier, the
  projects they are assigned to, and the documentation of every company they
  belong to. A platform admin is outside this and reaches everything, including
  every company they own.
- **Where there is no relationship, the snippet decides.** Each snippet declares
  itself public or internal, and that declaration is the only gate an outsider
  meets. Public material is readable by anyone with a legitimate reason to reach
  it; internal material is not readable without belonging.
<!-- /planned:docs-tier-layering -->

## Primary flows

**Gathering the tiers.** Read the global configuration, take the person and
company directories from their designated locations, and load the registered
project roots from the manifest. That set is the whole configuration surface;
there is no fifth place to look.

<!-- planned-change:docs-tier-layering -->
**Reading documentation.** Sources are aggregated into an index and the caller
sees the portion their clearance permits. Global and project documentation load
for the invocation's project. A project's owning company contributes that
company's documentation, drawn from the project's own declaration of which
company owns it — the declaration doing exactly its job.
<!-- change:docs-tier-layering -->
**Reading documentation.** Sources are aggregated into an index and the caller
sees the portion their relationships permit. Global documentation loads for
every caller. A project's owning company brings that company's documentation
into scope, drawn from the project's own declaration of which company owns it —
the declaration doing exactly its job — and the caller's own relationship to that
company decides how deeply it is read.
<!-- /planned-change:docs-tier-layering -->

<!-- planned:docs-tier-layering -->
**Deriving scope from the caller.** A caller's own person tier, their assigned
projects, and the documentation of every company they belong to are in scope
wherever they are working, independently of the directory they are in.
Someone with no relationship to a company is not shut out of it — they meet the
snippet's own declaration and read what is public, which is how a help desk
running inside a project registered to a company answers public questions for
people who do not belong to it. Explicit selectors naming a person or a company
override the derived scope and are available to platform admins only.
<!-- /planned:docs-tier-layering -->

## Failure modes

- **Assuming a scan.** Concluding that discovery walks the filesystem for
  `teleclaude.yml` leads to designs that add locations rather than registering
  them, and to resolution that depends on where an agent was started.
- **Letting git decide what a folder is.** Anchoring on a repository root makes a
  folder with a valid configuration fail because no `.git` sits above it, and
  lets an unrelated repository capture a configuration several levels down.
- **Reading scope from location.** Treating the current directory as the thing
  that sets what a caller may see produces an authorization model that changes
  when someone changes directory, which is not an authorization model.
- **Collapsing the two role axes.** Deriving a company role from a platform role,
  or the reverse, misreads identity across domains and grants authority nobody
  declared.
- **Grading access by company role.** Building tiers of documentation visibility
  inside a company invents a distinction the business does not have, and produces
  a permission matrix nobody asked for and no one can maintain.
- **Deriving project access from company membership.** Belonging to a company
  and being assigned to one of its projects are separate declarations. Treating
  the first as implying the second hands every member of a company every project
  it owns, which is the opposite of what assignment exists to express.
- **A tier that is modelled but unread.** A declared relationship with no
  consumer looks like a working feature and is not. Presence in the schema is
  not presence in behaviour.
