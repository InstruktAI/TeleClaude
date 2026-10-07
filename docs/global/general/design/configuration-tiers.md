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
- **The same manifest lists session homes.** A person or company home adopted
  onto the manifest is listed there as a place sessions run, and its own
  configuration declares its tier; that tier is still discovered at its
  designated location below, never through the manifest.
- **Every other tier lives at a designated location.** The global configuration
  is `~/.teleclaude/teleclaude.yml`. A person is
  `~/.teleclaude/people/<slug>/teleclaude.yml`. A company is
  `~/.teleclaude/companies/<slug>/teleclaude.yml`. These need no registry
  because their location is a convention, not a discovery problem.

**Output — the tier set for an invocation**, the documentation sources it
implies, and the portion of those sources the caller may see.

**Input — agent artifacts carry the same shape at every tier.** Each tier root
carries `agents/` beside `docs/`. In a repository, scope is in the path, exactly
as it is for documentation: `agents/{global,local}/{commands,skills}`.
In a company or person home the home is the scope, so `agents/{commands,skills}`
sits flat beside the home's two documentation halves, `docs/global` and
`docs/local`. Commands and skills are the two artifact
kinds; subagent definitions are not one — this platform's agents are general and
take their role from the command document they load. Global commands are partitioned by the
domains the repository publishes — `agents/global/commands/<domain>/` — under
the same one-owner declaration that governs documentation domains, `general`
included; global skills are the mother's alone. A
repository that carries global artifacts outside its declared reach fails
validation loudly. The open `.agents/` convention is never read as input.

<!-- planned:tier-command-corpus -->

**Output — artifacts are organized per consumer, not per tier.** Every consumer
finds artifacts where it natively looks, relative to the root a session runs
in: each native CLI's own directory (`.claude/`, `.codex/`, and the rest) at
every session-hosting root below the global one, the open `.agents/` convention
for skills, and one
TeleClaude command corpus per tier at `<root>/.teleclaude/commands/`, of which
the global corpus `~/.teleclaude/commands/<domain>/` is the instance at the
home root. A command exists exactly once per tier and is reached through the
loader by its explicit domain-namespaced name for global commands and its bare
name, resolved through the session's context, for tier-local ones; it is never
expanded into a per-CLI directory. Tier-local skills are native and eager:
a project's, company's, or person's skills duplicate into each CLI's directory
at the roots they reach. Global skills are catalog-only: they materialize under
`~/.teleclaude/skills/` and nowhere else, so the large general set stays lazy —
one index entry, listed on demand — rather than autoloaded into every session.

<!-- /planned:tier-command-corpus -->

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
- **The company tier carries who operates the business.** A company's
  configuration declares its people, the role each holds, and which of that
  company's projects each is assigned to. The person tier declares no company
  membership, so there is one authoritative place to read the relationship from
  and one place to change it.

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

<!-- planned:personal-assistant-project-creation -->

- **A home decides whose its projects are.** A project inside a person's or a
  company's home belongs to that home's owner, and is created only in that
  home's projects area. Ownership is a fact about where the project lives, read
  from the registries that designate each home; it is never a fact about where a
  caller stands. A project outside every home states its owner, or has none.
  Whose a project is and what kind a configuration file is are separate
  questions: the file's declaration alone answers the second.

<!-- /planned:personal-assistant-project-creation -->

<!-- planned:cross-tier-native-emission -->

- **Artifact reach follows ownership; documentation reach follows membership.**
  A caller sees the documentation of every company they belong to, from
  anywhere, because knowledge is inert. An artifact executes, so it reaches
  only the contexts that belong to its tier: global to every session, a
  company's to the projects declaring that company, a person's to that
  person's own workspace, a project's to itself. Membership never carries a
  skill into an unrelated context.
- **A generated artifact is capped at the tier that produced it.** Machine-
  authored artifacts have passed no human authoring or adoption gate; they
  reach no further than their producing tier, and promotion upward is a human
  act.

<!-- /planned:cross-tier-native-emission -->

- **Belonging is binary for reading a company.** A company role carries business
  authority; it does not grade documentation access. Anyone with a declared
  relationship to a company — member, contributor, whatever the role — reads that
  company's documentation in full. There are no levels of allowance inside a
  company.
- **Company membership does not carry that company's projects.** Belonging opens
  the company's own documentation. A project's documentation opens through the
  reach the roster resolves for the person: an explicit assignment to that
  project, or the company's administrative role, which covers everything that
  company owns. Documentation consumes that resolved reach as one answer and
  derives nothing from a role itself. Which declarations establish reach, and
  where they are declared, belong to the configuration tier; what documentation
  does with the answer belongs here.
- **A caller's relationship-derived scope is exactly three things.** Their own
  person tier, the documentation of every company they belong to, and full depth
  on every project they reach through the roster. The first two travel with the
  caller and are listed wherever they are working; the third is a depth, applied
  to the project being worked in or deliberately named, never a listing of every
  reached project. A platform admin is outside this and reaches everything,
  including every company they own.
- **Reach is wider than the relationship-derived part, and depth is not.** Global
  documentation is in every caller's scope because global is nobody's

<!-- planned-change:personal-assistant-project-creation -->

relationship, and the invocation itself offers the project it resolves to and
the company that project declares as its owner. Those sources enter reach
<!-- change:personal-assistant-project-creation -->

relationship, and the invocation itself offers the project it resolves to and
the company that owns that project. Those sources enter reach
<!-- /planned-change:personal-assistant-project-creation -->

without a relationship; what they do not do is grant the depth a relationship
grants. A caller holding no relationship to a source reads it at whatever its
snippets declare about themselves, which is what lets a help desk answer public
questions about a company it does not belong to.

- **Where there is no relationship, the snippet decides.** Each snippet declares
  itself public or internal, and that declaration is the only gate an outsider
  meets. Public material is readable by anyone with a legitimate reason to reach
  it; internal material is not readable without belonging.

- **Every documentation home has a published half and a local half.** A
  repository's, a person's, and a company's `docs/global` is published into the
  shared corpus; its `docs/local` is never published and is served in place from
  that home's own index. A local snippet's identity carries the `local/` prefix
  and a published snippet's does not, so the halves never share an identity and
  a snippet is named identically from every location. Which half a snippet lives
  in decides where it is served from; it decides who may read it only for a
  person's local half, which only that person and the system principal read
  (`general/policy/artifact-scope`).
- **Landing and reading are two mechanisms.** Where a session may run is decided
  by routing and folder scoping; what a caller may read is decided by identity,
  visibility, and the selectors the caller supplies. They meet at one point: the

<!-- planned-change:personal-assistant-project-creation -->

location an invocation lands in sets its default read set — that home (with,
for a project, the company it declares as its owner), the caller's own person
<!-- change:personal-assistant-project-creation -->

location an invocation lands in sets its default read set — that home (with,
for a project, the company that owns it), the caller's own person
<!-- /planned-change:personal-assistant-project-creation -->

tier, the companies they belong to, and global documentation. Location never
sets depth.

- **Any home is readable from anywhere by naming it.** A home selector names the
  home's published half, the local selector names its local half, and a qualified
  identity names the half its prefix states. The named half is read from
  wherever the caller stands, at the depth the caller's relationship grants; a
  person's local half refuses every caller but that person and the system
  principal.

## Primary flows

**Gathering the tiers.** Read the global configuration, take the person and
company directories from their designated locations, and load the registered
project roots from the manifest. That set is the whole configuration surface;
there is no fifth place to look.

**Reading documentation.** Sources are aggregated into an index and the caller
sees the portion their relationships permit. Global documentation loads for
every caller. A project's owning company brings that company's documentation
into scope, drawn from the project's own declaration of which company owns it —
the declaration doing exactly its job — and the caller's own relationship to that
company decides how deeply it is read.

**Deriving scope from the caller.** A caller's own person tier and the
documentation of every company they belong to are in scope wherever they are
working, independently of the directory they are in, together with the project
they are working in. The other projects they reach through the roster are read
in full when they work in one or name it; they do not enter the default listing.
Someone with no relationship to a company is not shut out of it — they meet the
snippet's own declaration and read what is public, which is how a help desk
running inside a project registered to a company answers public questions for
people who do not belong to it. Explicit selectors naming a person, a company, or
a project narrow the read to that tier's published half, or with the local
selector to its local half, and never widen it: the named half is loaded from
wherever the caller stands and read at the depth the caller's relationship
grants; a platform admin reads any named half in full except another person's
local half, which is refused.

## Failure modes

- **Assuming a scan.** Concluding that discovery walks the filesystem for
  `teleclaude.yml` leads to designs that add locations rather than registering
  them, and to resolution that depends on where an agent was started.
- **Letting git decide what a folder is.** Anchoring on a repository root makes a
  folder with a valid configuration fail because no `.git` sits above it, and
  lets an unrelated repository capture a configuration several levels down.
- **Reading authorization from location.** Treating the current directory as the
  thing that decides how deeply a caller may read produces an authorization model
  that changes when someone changes directory, which is not an authorization
  model. Location chooses only which homes are listed by default.
- **Reading confidentiality from the half.** Treating `docs/local` as private or
  `docs/global` as public puts a snippet's audience in the folder it was filed
  in. Visibility and the caller's relationship decide reading in both halves of
  every project and company home; a person's local half is the one exception,
  owner-only by rule rather than by `visibility`.
- **Collapsing the two role axes.** Deriving a company role from a platform role,
  or the reverse, misreads identity across domains and grants authority nobody
  declared.
- **Grading access by company role.** Building tiers of documentation visibility
  inside a company invents a distinction the business does not have, and produces
  a permission matrix nobody asked for and no one can maintain.
- **Deriving project access from company membership.** Belonging to a company
  and reaching one of its projects are separate declarations. Treating the first
  as implying the second hands every member of a company every project it owns,
  which is the opposite of what assignment exists to express. The company's
  administrative role is the one declaration that covers all of them, and the
  roster resolves it; documentation never infers it from a role on its own.
- **A tier that is modelled but unread.** A declared relationship with no
  consumer looks like a working feature and is not. Presence in the schema is
  not presence in behaviour.

- **Reading authored input from a location the platform writes.** Treating the
  open `.agents/` directory, or any delivery location, as a source root makes a
  file's provenance unreadable from its path and lets a regenerating deploy
  overwrite authored work. Sources and outputs never share a location.
