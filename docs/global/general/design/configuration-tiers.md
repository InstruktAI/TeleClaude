---
description: How TeleClaude finds its configuration files across the global, person, company, and project tiers, how those tiers relate to each other, and how that relationship governs what a caller may read.
---

# Configuration Tiers — Design

## Purpose

One filename, `teleclaude.yml`, carries configuration at every tier. This design
states where those files are, how each one is found, how the tiers relate to one
another, and why that relationship is the thing that decides what any given
caller is allowed to read.

It exists because an agent that has to reconstruct this from the code gets it
wrong in a predictable direction: it assumes discovery is a filesystem scan, it
assumes git decides what is what, and it treats the folder an agent happens to
be standing in as the thing that sets scope. None of those is true, and each
wrong assumption produces a plausible design that has to be undone.

## Inputs/Outputs

**Input — two discovery mechanisms, no scanning.**

- **Projects self-register.** A project may live anywhere on disk, so it cannot
  be found by convention. Its root is recorded in the manifest at
  `~/.teleclaude/projects.yaml`, which stores roots only; each root's
  `teleclaude.yml` is then read to hydrate the project. Nothing walks the
  filesystem looking for projects.
- **Every other tier lives at a conventional location and is traversed.** The
  global configuration is `~/.teleclaude/teleclaude.yml`. A person is
  `~/.teleclaude/people/<slug>/teleclaude.yml`. A company is
  `~/.teleclaude/companies/<slug>/teleclaude.yml`, enumerated by listing that
  directory. These need no registry because their location is designated.

**Output — the tier set for an invocation**, and from it the set of documentation
sources and the portion of them the caller may see.

## Invariants

- **Meaning comes from the file, never from where it sits.** A configuration
  file states what it is. Location is how conventional tiers are *found*; it is
  never what makes them *mean* something.
- **Git has nothing to do with discovery.** That a folder sits inside a git
  repository, at any depth, is irrelevant to finding TeleClaude configuration.
  Git answers a different question — where a project's shared state lives when
  a linked worktree is in play — and that question exists only for projects.
  Committing is likewise separate: a commit works from any folder with a parent
  git configuration.
- **Persons and companies are not repositories of their own.** Their content is
  committed in the `~/.teleclaude` home repository. Projects commit to their
  own.
- **A company folder is a registry identity, not a place an agent's scope is
  derived from.** Standing inside one confers nothing.
- **Relationships are declared, not inferred.** A project declares its owning
  company in its own configuration. A person declares the companies they belong
  to, and their role in each, in theirs. Neither is deduced from paths.
- **Platform role and company role are independent axes.** The platform role
  governs authority over TeleClaude itself. A company role states one person's
  relationship to one business. A person may be a member of one company and an
  admin of another, and neither fact follows from the other.
- **Belonging is binary for reading.** A company role carries business
  authority; it does not grade documentation access. Anyone with a declared
  relationship to a company — member, contributor, whatever the role — reads
  that company's documentation in full. There are no levels of allowance inside
  a company.
- **Where there is no relationship, the snippet decides.** Each snippet declares
  itself public or internal, and that declaration is the only gate an outsider
  meets. Public material is readable by anyone with a legitimate reason to reach
  it; internal material is not readable without belonging.

## Primary flows

**Gathering the tiers.** Read the global configuration; enumerate the person and
company directories; load the registered project roots from the manifest. That
set is the whole configuration surface — there is no fifth place to look.

**Deriving a caller's scope.** The gathered set carries the relationships, and
the relationships carry the authorization. A caller resolves to a person, and
that person's declared company memberships decide which company tiers are open
to them in full. This is a property of who the caller is, not of where they are
working.

Someone with no relationship to a company is not thereby shut out of it. They
meet the snippet's own declaration instead, and read what is marked public. That
is how a help desk running inside a project registered to a company answers
public questions about that company for people who do not belong to it, while
its internal material stays unreachable.

**Reading documentation.** Sources are aggregated into an index, and the caller
sees the portion of it their scope permits. Global and project documentation
load as they do today. A project's owning company contributes that company's
documentation — this is the project's own declaration doing its job, and it is
correct.

<!-- planned:docs-tier-layering -->
A caller's own memberships contribute independently of any project: the
documentation of every company they belong to, and their own person tier, are in
scope wherever they are working. Explicit selectors — a person or a company named
on the command line — override the derived scope and are available to platform
admins only.
<!-- /planned:docs-tier-layering -->

## Failure modes

- **Assuming a scan.** Concluding that discovery walks the filesystem for
  `teleclaude.yml` leads to designs that add locations rather than registering
  them, and to resolution that depends on where an agent was started.
- **Letting git into resolution.** Anchoring on a repository root makes a folder
  with a valid configuration fail because no `.git` exists above it, and makes
  an unrelated repository capture a configuration several levels down.
- **Reading scope from location.** Treating the current directory as the thing
  that sets what a caller may see produces an authorization model that changes
  when someone changes directory, which is not an authorization model.
- **Collapsing the two role axes.** Deriving a company role from a platform role,
  or the reverse, misreads identity across domains and grants authority nobody
  declared.
- **Grading access by company role.** Building tiers of documentation visibility
  inside a company — this role sees more than that one — invents a distinction
  the business does not have, and produces a permission matrix nobody asked for
  and no one can maintain.
- **A tier that is modelled but unread.** A declared relationship with no
  consumer looks like a working feature and is not. The membership field exists
  before anything reads it; presence in the schema is not presence in behaviour.
