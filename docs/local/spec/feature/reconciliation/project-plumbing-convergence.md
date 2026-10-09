---
description: Convergence of a root to its declaration — a project's installed git plumbing
  and help desk, and the masters and help desks the platform home seeds from templates — performed
  at project initialization, at the commit boundary and by an on-demand maintenance run,
  and never by publication.
visibility: internal
---

# Project Plumbing Convergence — Spec

## What it is

A project's installed git plumbing is machine state: the TeleClaude-owned
`pre-commit`, `pre-merge-commit`, `post-commit`, `post-merge` and `pre-push`
hooks under the git directory and the `teleclaude-docs` filter driver in the
repository's own git config. Neither is tracked by the project, so a clone
carries neither. The `pre-merge-commit` hook runs the same commit gate as
`pre-commit`, so a merge commit git creates without a separate `git commit`
passes that gate too (`local/projects/teleclaude/spec/feature/agent_runtime/sealed-commit`).

The project's configuration-schema link is machine state in the same way: a
symbolic link in the project's machine-local state directory, which the project
never tracks, pointing at the TeleClaude home's published schemas
(`local/projects/teleclaude/spec/feature/reconciliation/config-schema-publication`). A project's
committed configuration files reference their schemas through that link, so the
same committed reference resolves on every machine that carries its own link.
The link's location is the one the configuration writer's project-tier
reference names (`teleclaude/config/declaration.py`).

Convergence is the act of comparing that observed machine state against the
project's capability declaration and performing the sanctioned actions that
close the gap. It is reconciliation's rule. The declaration it reads is
`config`'s published contract
(`local/projects/teleclaude/spec/feature/config/project-capability-manifest`), consumed at the
crossing and never restated here; what the converged plumbing then does — what
the hooks check, what the docs pipeline processes — belongs to the contexts that
own those behaviors.

A root's declaration also decides which masters convergence seeds into it: a
project's help desk while the project's declaration enables one, and, in the
platform home — the repository declaring the global tier, which holds the
person and company homes — each declared person and company home's master and
each company help desk its company's declaration enables. Each is seeded from
its kind's template only while absent, and then belongs to its home, whose
history records it
(`local/projects/teleclaude/spec/feature/reconciliation/home-template-materialization`).

Convergence runs at project initialization for a project. Machine installation
converges the machine plumbing of the platform home and of the TeleClaude
checkout, and seeds no master. An on-demand maintenance run
(`telec sync`, `local/projects/teleclaude/spec/feature/integration/on-demand-maintenance`)
performs the whole act for the root it runs in, as one of that root's
maintenance steps. Publication performs none of it: deploying committed sources
installs, refreshes and withdraws nothing, and the read-only gate touches
nothing.

Convergence additionally runs without an initialization or an installation at
the commit boundary, whenever an advancement of a canonical checkout's main
branch changes what a root's convergence produces:

- a project commit changing the project's declaration while that declaration
  enables a help desk converges that project, and the project's publication
  then follows it;
- a platform-home commit changing the global declaration or a person or
  company declaration converges the platform home, and the platform home's
  publication then follows it;
- a TeleClaude commit changing a TeleClaude-owned hook template, help-desk
  template or home master template converges every registered root on that
  machine and the platform home, and TeleClaude's publication then follows it.

The act is the one initialization already performs — the same comparison
against the template, the same sanctioned actions, the same preservation of a
root's own hooks — reached by a different trigger. It remains outside
publication.

## Canonical fields

- **Hooks.** A project receives the TeleClaude-owned hook set when any enabled
  capability or declared binding can resolve an executable action. A hook the
  project authored itself is preserved rather than overwritten. A project with
  no executable binding receives no TeleClaude-owned hook. A project-authored
  hook may itself invoke `telec code <hook-name>` as one of its own steps, so
  TeleClaude's dispatch and logic the platform cannot express run from the same
  file; it still carries no sentinel and is still preserved exactly as any
  project-authored hook is — it does not converge when the platform's template
  next changes, so leaving it in place is recorded rather than treated as
  ordinary, silent preservation.
- **Filter driver.** The driver is present exactly when the project subscribes
  `docs`. Convergence is two-directional: the driver is installed when `docs` is
  subscribed and removed when it is not, so the act runs regardless of the
  declaration's value.
- **Repair.** Tracked files a checkout left unexpanded, and files still carrying
  a prior filter pattern's residue, are re-checked out so the smudge filter
  applies to them. A locally modified file is left untouched. Repair resolves a
  file's filter attribute, so it runs after the filter attributes are written.
- **Schema link.** Every adopted project carries the link, whatever it
  subscribes. Before the link exists, the repository's local exclude list names
  its path, so the link is never offered for commit whatever the project's own
  ignore rules say; the exclude list is untracked repository state shared by the
  checkout and its worktrees. An absent link is created, a link pointing
  elsewhere is repointed, and a correct link is left untouched. A directory or
  file already occupying the link path is reported and left untouched.
- **Local state exclusion.** Every adopted project's local exclude list names
  TeleClaude's machine-local state in that project — its `.teleclaude/`
  directory and the configuration writer's lock files — whatever the project
  subscribes and whatever its own ignore rules say. A missing name is added and
  a present one is left as it is.
- **Stray schema copies.** A per-project schema copy left at the project root is
  removed when the project does not track it and it holds nothing but
  TeleClaude's generated schema files. A tracked copy,
  or one holding anything else, is reported and left untouched: removing it is
  a commit in that project, which convergence never makes.
- **Reporting.** A retained stray copy and an occupied link path are reported
  for the root without failing its convergence. Neither affects the hooks or
  the filter driver.
- **Help desk.** A project whose declaration enables a help desk has its
  `help-desk/` folder seeded from the project help-desk template on every
  convergence: an absent master is written and an existing one is left as it
  is, whatever its content; the desk's ignore file converges to its template.
  A project whose declaration does not enable one has nothing seeded, and a
  desk folder left from an earlier enabling stays in place, no longer hosted.

- **Platform home masters.** The platform home's convergence seeds each
  declared person and company home's master and each enabled company desk the
  same way. The home's root master has no template and is never
  written. It converges no plumbing of the home, which machine
  installation owns. A person or company home is declared when its folder
  holds its tier declaration.

- **No existing master is written.** Convergence writes untracked machine state,
  a desk's ignore file, and masters that are absent. A master that exists is
  never rewritten, so a recorded master never leaves its home's working tree
  dirty. The one other project-tracked file TeleClaude ever writes is the
  `.gitattributes` docs-filter line, written additively at adoption by its own
  step and never touched by a later convergence.
- **Installation converges machine plumbing only.** Machine installation's
  convergence of the TeleClaude checkout and of the platform home performs the
  hooks, filter driver and schema link fields above and seeds no help desk and
  no master.
- **Fleet convergence is one operation.** A single operation converges every
  registered project root on the machine and the platform home: it enumerates
  the project entries of the project registry — a person or company home on it
  is part of the platform home — compares each root's installed plumbing and
  seeded masters against the current templates and its declaration, and
  performs only the actions that close a gap. It is what TeleClaude's
  commit-boundary trigger invokes, and it is invocable on its own. A root that
  already matches is left untouched, an unavailable root is reported rather
  than failing the run, and roots on other machines are outside its reach.

### Use cases

#### UC-RPC1: Convergence removes the driver when docs is unsubscribed

```gherkin
Given a project whose git config carries the TeleClaude docs filter driver
And the project's declaration does not subscribe docs
When an agent runs project initialization for that project
Then the docs filter driver is removed from the project's git config
And no project-tracked file is edited
```

#### UC-RPC2: Convergence installs the driver and repairs an unexpanded checkout

```gherkin
Given a project subscribing docs whose filter attributes are written
And whose tracked documentation still holds unexpanded portable references
When an agent runs project initialization for that project
Then the docs filter driver is configured in the project's git config
And those documentation files read as absolute home paths in the working copy
And a file carrying local modifications keeps its local content
```

#### UC-RPC3: Convergence refreshes TeleClaude's hooks and preserves the project's own

```gherkin
Given a project whose enabled capabilities or declared bindings resolve an executable action
And whose installed hooks include hooks TeleClaude owns
And which also carries a hook the project authored itself
When an agent runs project initialization for that repository
Then the TeleClaude-owned hooks are refreshed from their current templates
And the project-authored hook is left in place
```

#### UC-RPC17: A project-authored hook that itself calls TeleClaude's dispatch is preserved

```gherkin
Given a project-authored hook that carries no TeleClaude sentinel
And that hook itself invokes telec code <hook-name> alongside its own logic
When an agent runs project initialization or fleet convergence for that project
Then that hook is left in place, unmodified
And it is not converged when the platform's hook template next changes
```

#### UC-RPC4: A project subscribing neither receives no git plumbing

```gherkin
Given a repository whose declaration activates no executable action binding
And whose declaration does not subscribe docs
When an agent runs project initialization for that repository
Then no TeleClaude-owned git hook is installed for it
And no docs filter driver is configured for it
```

#### UC-RPC7: Machine installation converges the platform home's plumbing

```gherkin
Given the platform home repository, declaring the global tier and holding person and company documentation homes
When the machine installation target runs
Then TeleClaude's hooks and the docs filter driver are installed in the home's git directory when absent
And an installed hook is rewritten only when the content rendered from TeleClaude's hook template differs from what is installed, and is otherwise left untouched
And hooks the home carries that TeleClaude does not own are preserved
And a repeated run with nothing changed writes nothing
```

#### UC-RPC6: Publication converges no project plumbing

```gherkin
Given a project whose git hooks and docs filter driver are both out of date
When publication deploys that project's committed sources
Then no git hook is installed or refreshed
And the docs filter driver is neither configured nor removed
```

#### UC-RPC8: A changed hook template converges every registered root

```gherkin
Given a TeleClaude-owned hook template has changed
And that change advances the canonical checkout's main branch
When the commit-boundary maintenance runs
Then every registered root on that machine converges its installed plumbing
And a root whose installed plumbing already matches its template is left untouched
And a hook a root authored itself is preserved
And no tracked file is written and no commit is produced in any converged root
```

#### UC-RPC9: Machine installation converges this checkout through the same act

```gherkin
Given the TeleClaude checkout carries a hook TeleClaude does not own
And one of its TeleClaude-owned hooks lags its current template
And another already matches its current template
When the machine installation target runs
Then the lagging hook is refreshed from its template
And the hook already matching its template is not rewritten
And the hook the checkout authored itself is preserved
And every hook in the TeleClaude-owned set is covered, none omitted
And the checkout's docs filter driver is configured
```

#### UC-RPC11: One act converges plumbing, whatever triggers it

```gherkin
Given plumbing is converged from project initialization, from machine installation, from the commit-boundary trigger, and from an on-demand maintenance run
When any of those paths runs
Then each performs the same comparison against the current templates
And each preserves a hook its root authored itself
And no trigger carries an installer whose semantics differ from the others
```

#### UC-RPC10: An unavailable root does not fail the convergence run

```gherkin
Given the registry names a root that is not present on this machine
When fleet convergence runs
Then that root is reported as unavailable
And every other registered root still converges
```

#### UC-RPC12: Convergence links an adopted project to the published schemas

```gherkin
Given an adopted project whose root carries no configuration-schema link, or a link pointing elsewhere
When an agent runs project initialization or fleet convergence for that project
Then the project's configuration-schema link points at the TeleClaude home's published schema directory
And the schema reference in the project's committed configuration resolves to the published project schema
And the link does not appear among the project's untracked files
And no project-tracked file is edited
```

#### UC-RPC13: Convergence removes a stray untracked schema copy

```gherkin
Given an adopted project whose root holds a schema copy the project does not track
And that copy holds only TeleClaude-generated schema files
When an agent runs project initialization or fleet convergence for that project
Then that schema copy is removed
And the project's convergence completes successfully
```

#### UC-RPC14: A tracked or foreign schema copy is reported and kept

```gherkin
Given an adopted project whose root holds a schema copy that the project tracks or that holds a file TeleClaude did not generate
When an agent runs fleet convergence
Then that copy and every file in it are left in place
And the agent sees that root reported as retaining a schema copy
And no commit is made in that project
And every other registered root still converges
```

#### UC-RPC15: An occupied link path is reported and kept

```gherkin
Given an adopted project whose configuration-schema link path is occupied by a directory or a regular file
When an agent runs fleet convergence
Then the occupying entry is left unchanged
And the agent sees that root reported as having its schema link path occupied
And the project's hooks and docs filter driver still converge
```

#### UC-RPC18: An adopted project never offers TeleClaude's local state for commit

```gherkin
Given a folder with no git repository and no TeleClaude configuration
When an operator adopts it with `telec config project adopt`
Then the operator's `git status` in that folder lists neither the project's TeleClaude state directory nor the configuration lock file
And the same holds for a project that subscribes neither code nor docs
```

#### UC-RPC19: An on-demand maintenance run converges the root it runs in

```gherkin
Given a project whose installed TeleClaude-owned hooks lag their current templates
And which also carries a hook the project authored itself
And whose docs filter driver does not match its docs subscription
When an agent runs telec sync in that project's canonical checkout on main
Then the project's TeleClaude-owned hooks are refreshed
And the project-authored hook is left in place
And the docs filter driver matches the project's docs subscription
And no tracked file is written and no commit is produced
```

## Known caveats

- A master convergence seeds is not recorded by it. Its entrypoint is compiled
  by the publication that follows the commit recording it in its home
  (`local/projects/teleclaude/spec/feature/context/sync-pipeline-orchestration`).
- A changed master template reaches no existing master: convergence seeds only
  absent masters, so an existing master changes only by its home's edit.
- A changed hook template reaches a machine's registered roots when that change
  reaches the machine's canonical checkout, so installed plumbing lags only
  between a template change and its arrival there; a machine that has not
  received it has nothing newer to install. The capability declaration itself
  needs no reinstallation to take effect, because the installed plumbing reads
  it on each invocation.
- The TeleClaude checkout's own hooks and filter driver, and the platform
  home's, are installed by the machine installation target, which is not a
  project initialization path; between one installation and the next the
  home's plumbing can lag a changed hook template exactly as a project's can,
  until an installation or an on-demand maintenance run in the home converges it.
