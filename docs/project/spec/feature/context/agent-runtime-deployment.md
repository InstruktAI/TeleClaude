---
description: 'Two-phase deployment of transpiled artifacts to per-agent home dirs, with Codex commands routed to a shared TeleClaude dir and global docs composed as a per-domain symlink with exactly one owning publisher per domain.'
visibility: 'public'
---

# Agent Runtime Deployment — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is


The phase of Sync that writes Deployed outputs each agent CLI reads at
runtime. When invoked via `telec sync`, the distribution step always runs
in deploy mode (there is no no-deploy mode through the CLI). The deploy
path runs two phases:


<!-- planned-change:agent-artifact-source-layout -->

1. **Global phase** — sources from `agents/` (Mother project only) are
   built under a transient distribution directory and then deployed
   to per-agent user-home roots: `~/.claude/`, `~/.gemini/`, `~/.codex/`.
   The publishing gate ensures the global agent-artifact source list is
   only populated on the Mother project. Global documentation, in contrast,
   is contributed by every project for the domains it publishes (see below).

<!-- change:agent-artifact-source-layout -->

1. **Global phase** — sources from `agents/global/` (general commands and
   skills from the mother alone; domain-partitioned commands
   from every repository for the domains it publishes) are built under a
   transient distribution directory and deployed to the global consumers:
   the per-agent user-home roots, the global command corpus
   `~/.teleclaude/commands/<domain>/`, and the global skill catalog. A
   repository carrying global artifacts outside its declared reach fails
   validation rather than being silently skipped.

<!-- /planned-change:agent-artifact-source-layout -->

<!-- planned-change:agent-artifact-source-layout -->

2. **Local phase** — sources from `.agents/` (any project) are built
   under a transient distribution directory and then deployed to the
   project root.

<!-- change:agent-artifact-source-layout -->

2. **Local phase** — sources from `agents/project/` (any repository) are
   built under a transient distribution directory and then deployed to that
   project's own runtime locations. `.agents/` is one of those delivery
   locations, never an input.

<!-- /planned-change:agent-artifact-source-layout -->

<!-- planned-change:agent-artifact-source-layout -->

Global skill publication is a separate composed surface. Every registered
project contributes each direct `agents/skills/<name>/` folder; no configuration
capability is required because folder existence is the declaration. Sync
materializes the contributed packages under `~/.teleclaude/skills/` and the
Mother project alone supplies the catalog `AGENTS.master.md`. Side-project
catalog masters are not parsed. After the skill links exist, the Mother-owned
catalog master runs through the normal renderer and its generated `AGENTS.md` is
written into the deployed catalog as an orientation note carrying no index. The
listing is rendered on demand by `general/procedure/skill-use`, which
`AGENTS.global.md` carries as a curated index entry and never as an `@` ref, so
the skill catalog stays lazy rather than being preloaded.
<!-- change:agent-artifact-source-layout -->

Global skill publication is the mother's alone: `agents/global/skills/<name>/`
folders in the mother repository materialize under `~/.teleclaude/skills/`, and
the mother supplies the catalog `AGENTS.master.md`. A side project's global
skills are refused at validation; a project that authors a portable skill
contributes it to the mother, which is the curation step. The catalog master
runs through the normal renderer after the skill links exist, its generated
`AGENTS.md` orients readers to the directory without indexing it, and the
listing is rendered on demand by `general/procedure/skill-use` — reached from
`AGENTS.global.md` as a curated index entry, never an `@` ref — so the global
catalog stays lazy. Tier-local skills are the ones that reach native CLI
directories, eager-indexed in their context's generated entrypoint.
<!-- /planned-change:agent-artifact-source-layout -->

<!-- planned-change:command-migration-to-singular-telec-skill -->

Codex commands are an exception: they route to
`~/.teleclaude/commands/` (NOT `~/.codex/commands/`) so commands are
reusable across projects.

<!-- change:command-migration-to-singular-telec-skill -->

TeleClaude command artifacts are not runtime artifacts at all: command
documents deploy to `~/.teleclaude/commands/` from the global phase alone,
and no per-agent runtime receives any command artifact — native or
otherwise. Commands are reached exclusively through the loader message
TeleClaude composes at dispatch (and for machine-emitted procedure loads),
which instructs the session to read the corpus document directly. The global
corpus is the existing `~/.teleclaude/commands/` directory and is reusable
across projects. Domain partitioning of that directory, per-tier corpora, and
bare-name resolution across tiers are later contracts
(`agent-artifact-source-layout`, `tier-command-corpus`) that this one does
not foreclose: the loader accepts an optional domain segment in a name.

Global skills compose to `~/.teleclaude/skills/` and are discovered through the
catalog the master points at; they reach no runtime home. Tier-local skills
(`.agents/skills/**`) materialize into the native CLI skill directories at
their root, because being preloaded is their purpose. Subagent definitions are
not an artifact class. Beyond tier-local skills, the entrypoint master is the
only per-agent output, written where each CLI reads it unprompted — for the Antigravity CLI (`agy`) that is the configured
`context.fileName` (`AGENTS.md`) under `~/.gemini/antigravity-cli/`. The
legacy Node Gemini CLI layout — `~/.gemini/commands/`, `~/.gemini/skills/`,
`~/.gemini/agents/`, and `~/.gemini/GEMINI.md` — is obsolete and is no longer
provisioned. Content in any runtime home that this pipeline did not produce is
left untouched.

<!-- /planned-change:command-migration-to-singular-telec-skill -->

After both phases, the global documentation tree is exposed at
`~/.teleclaude/docs/` as a **per-domain composition with exactly one owning
publisher per domain**. The root is a real directory rebuilt each sync. Each
published domain is a single symlink `~/.teleclaude/docs/<domain>` → the owning
publisher's `docs/global/<domain>/` directory; the cross-cutting `general/` is a
single symlink to the Mother repo's `docs/global/general`. A symlink has exactly
one target, so one-owner-per-domain is structural — two publishers cannot merge
into one domain. A domain's snippet files resolve through the directory symlink
as live views of the owner's source (no copy). The valid domains are exactly the
union of every registered project's `business.publishes`; TeleClaude holds no
central allow-list of valid domains, and adding a domain needs only a project
that declares and serves it.

<!-- planned-change:agent-artifact-source-layout -->

The registered-publisher set is maintained automatically: a deploy-mode
`telec sync` from a project declaring `business.publishes` or containing a
direct `agents/skills/<name>/` folder registers that project's durable root.
The folder is the skill-publication declaration; no separate configuration
capability or registration step exists. Split detection (below) evaluates every
registered domain publisher, so a self-registered publisher participates in the
one-owner-per-domain hard block like any other.

<!-- change:agent-artifact-source-layout -->

The registered-publisher set is maintained automatically: a deploy-mode
`telec sync` from a project declaring `business.publishes` registers that
project's durable root. Split detection (below) evaluates every registered
domain publisher, so a self-registered publisher participates in the
one-owner-per-domain hard block like any other, for documentation and for
domain-partitioned global commands alike.

<!-- /planned-change:agent-artifact-source-layout -->
Sync-time split detection runs before composition: if more than one registered
project declares the same domain in `business.publishes`, the deploy
HARD-BLOCKS (exits non-zero, composes nothing) with `split domain ownership:
<domain> claimed by <A> and <B>`. The single declaring project is the owner
whose folder the domain symlinks to. This is the one cross-publisher integrity
rule: a domain has exactly one owning publisher.

The deploy writes the merged `index.yaml` at the root — the union of every
owner's per-domain global index. Because no two owners share a domain, the union
carries no cross-owner id collision to resolve. The single filesystem root
`~/.teleclaude/docs` is preserved so the three readers that resolve global docs —
the SessionStart hook, `telec docs`, and the index build — read one root
unchanged.


For each published domain the deploy inflates the owner's `baseline.md` and
`baseline-progressive.md`, then writes the result as `domain-baseline-bundle.md`
**inside the owner's `docs/global/<domain>/` directory** (gitignored in the
source tree). Because `~/.teleclaude/docs/<domain>` is a symlink to that
directory, `~/.teleclaude/docs/<domain>/domain-baseline-bundle.md` resolves
through it. With one owner per domain the bundle is single-source: there is no
cross-publisher dedup. Documentation composition and bundle generation complete
before agent artifacts are transpiled, so a procedure that needs the generated
bundle names it as an explicit Required Read. The transpiler expands that bundle
into the consuming artifact; SessionStart does not select or inject command-domain
baseline context.

Global third-party docs are read from the mother repo source (`docs/third-party/`),
not from under the docs tree.

When the distribution step is invoked directly in no-deploy mode, agent
artifacts are emitted to `project_root/dist/global` and
`project_root/dist/local` (not transient dirs), no copies are made to
`~/.<agent>/`, and documentation deployment is skipped. This direct
no-deploy mode is for developers/CI inspecting build output.

## Canonical fields

Deployment is scoped to projects subscribing the `agents` capability
(`project/spec/feature/config/project-capability-manifest`). For a project that
does not subscribe it, neither transpilation phase nor artifact deployment runs;
documentation publication is governed independently by the `docs` capability.

The behavioral contract is `UC-CFG-CAP-18` in
`project/spec/feature/config/project-capability-manifest`; this spec references that scenario
rather than restating it.

### Use cases

```
Scenario: UC-ARD1 Mother project full sync with deploy
  Given the project is the Mother project
  And sync is invoked in deploy mode
  When the distribution pipeline runs
<!-- planned-change:command-migration-to-singular-telec-skill -->
  Then global sources from agents/ deploy to ~/.claude/, ~/.gemini/, and ~/.codex/
  And local sources from .agents/ deploy to the project root
  And Codex commands deploy to ~/.teleclaude/commands/
<!-- change:command-migration-to-singular-telec-skill -->
  Then the entrypoint master from agents/ deploys to each enabled runtime's home
  And TeleClaude command artifacts from agents/ deploy to ~/.teleclaude/commands/
  And skill packages compose to ~/.teleclaude/skills/
  And no command, global skill, or subagent artifact is written into any runtime home
<!-- /planned-change:command-migration-to-singular-telec-skill -->
  And AGENTS.override.md is written to the project root for Codex override detection
  And docs/global/ is composed per domain into the ~/.teleclaude/docs/ root
```

```
Scenario: UC-ARD2 Non-mother project sync skips global agent-artifact phase
  Given the project is not the Mother project
  And sync is invoked in deploy mode
  When the distribution pipeline runs
<!-- planned-change:command-migration-to-singular-telec-skill -->
  Then the global phase produces no agent-home artifact writes
  And the local phase deploys .agents/ to the project root
  And Codex commands still route to ~/.teleclaude/commands/
<!-- change:command-migration-to-singular-telec-skill -->
  Then the global phase produces no agent-home artifact writes
  And the local phase materializes tier-local skills from .agents/skills/ into the project-root CLI skill directories
  And the local phase writes no command artifact and no subagent definition anywhere
  And how a project-local command source is handled is owned by the later tier corpus contract, not by this phase
<!-- /planned-change:command-migration-to-singular-telec-skill -->
  And each domain the project owns in business.publishes is a single symlink ~/.teleclaude/docs/<domain> to the project's docs/global/<domain>
```

#### UC-ARD3: Deploy is refused from a slug worktree

```
Scenario: UC-ARD3 Deploy is refused from a slug worktree
  Given a deploy-mode sync runs from a slug worktree of the Mother project
  When the pipeline starts
  Then the deploy is refused with a sync-blocking error naming the slug worktree
  And nothing is composed and the deployed docs root is left unchanged
  And deploy from the main checkout or the integration worktree is unaffected
```

```
Scenario: UC-ARD4 Sync composes the per-domain single-owner docs tree
  Given two publishers, each declaring in business.publishes a different domain it owns
  When the documentation deployment step runs
  Then any stale real or symlinked ~/.teleclaude/docs from an older deploy is replaced
  And ~/.teleclaude/docs is a real directory
  And each published domain is a single symlink ~/.teleclaude/docs/<domain> to its owning publisher's docs/global/<domain> directory
  And ~/.teleclaude/docs/general resolves to the Mother repo's docs/global/general
  And ~/.teleclaude/docs/index.yaml is the union of every owner's global index
  And each published domain's domain-baseline-bundle.md resolves through the domain symlink to the owner's source directory
  And a snippet removed from a source domain disappears from ~/.teleclaude/docs/<domain> on the next deploy with no orphan link
```

```
Scenario: UC-ARD5 Distribution invoked directly in no-deploy mode
  Given the distribution step is invoked directly (not through telec sync) in no-deploy mode
  When the distribution pipeline runs
  Then agent artifacts are emitted under project_root/dist/global and project_root/dist/local
  And no transient distribution dirs are used
  And no writes occur to ~/.claude/, ~/.gemini/, ~/.codex/
  And documentation deployment is NOT performed
  And the dist/ output is left in place for inspection
```

#### UC-ARD13: A generated domain bundle resolves as an explicit Required Read

```
Scenario: UC-ARD13 A generated domain bundle resolves as an explicit Required Read
  Given a procedure names ~/.teleclaude/docs/<domain>/domain-baseline-bundle.md as a Required Read
  And the domain has exactly one registered publisher
  When deploy mode runs
  Then documentation composition generates the current domain bundle before agent-artifact transpilation
  And the transpiler expands the generated bundle into each consuming artifact exactly once
  And validation accepts the canonical generated-bundle path without treating it as an authored snippet
  And a generation or resolution failure aborts before previously deployed agent artifacts are replaced
```

```
Scenario: UC-ARD6 A procedure carries its generated domain bundle explicitly
  Given a procedure requires a generated domain baseline bundle
  And its Required reads name ~/.teleclaude/docs/<domain>/domain-baseline-bundle.md
  When agent artifacts are transpiled
  Then the bundle is expanded into the consuming artifact exactly once
  And the artifact does not depend on SessionStart command-domain selection
```

```
Scenario: UC-ARD7 A missing generated bundle blocks artifact deployment
  Given a procedure Required read names a generated domain baseline bundle
  And that generated bundle is absent
  When agent artifacts are validated or transpiled
  Then deployment fails before previously deployed artifacts are replaced
  And SessionStart does not resolve, warn about, or inject the missing domain bundle
  And unrelated SessionStart additional-context duties remain unchanged
```


```
Scenario: UC-ARD8 Split domain ownership blocks the deploy
  Given two registered publishers that both declare the same domain in business.publishes
  When the documentation deployment step runs
  Then the deploy aborts with a sync-blocking error naming the split domain and both publishers
  And nothing is composed and no merged index is written
```

<!-- planned-change:agent-artifact-source-layout -->

#### UC-ARD11: Registered projects compose one lazy global skill catalog

```
Scenario: Skill folders publish globally by existence
  Given the Mother project and one or more registered side projects contain agents/skills/<name>/ folders
  And only the Mother project owns agents/skills/AGENTS.master.md
  When sync runs in deploy mode
  Then each named skill folder is materialized in ~/.teleclaude/skills/<name>/
  And side-project AGENTS.master.md and AGENTS.md files under agents/skills are not parsed or published
  And package Markdown is not validated against TeleClaude's authored-artifact taxonomy
  And the Mother-owned catalog master is rendered after the deployed skill links exist
  And ~/.teleclaude/skills/AGENTS.md orients readers to the directory without indexing it
  And the global agent baseline carries a curated index entry for general/procedure/skill-use
```

<!-- change:agent-artifact-source-layout -->

#### UC-ARD11: The mother composes one lazy global skill catalog

```
Scenario: The mother's skill folders publish globally by existence
  Given the mother repository contains agents/global/skills/<name>/ folders
  And a registered side project contains agents/global/skills/<name>/ folders
  When sync runs in deploy mode
  Then each mother skill folder is materialized in ~/.teleclaude/skills/<name>/
  And the side project's global skill folders are refused with a message naming the files
  And package Markdown is not validated against TeleClaude's authored-artifact taxonomy
  And the Mother-owned catalog master is rendered after the deployed skill links exist
  And ~/.teleclaude/skills/AGENTS.md orients readers to the directory without indexing it
  And the global agent baseline carries a curated index entry for general/procedure/skill-use
```

<!-- /planned-change:agent-artifact-source-layout -->
#### UC-ARD9: Published-domain activatable procedures are scoped to global agent output

```
Scenario: UC-ARD9 A published domain's activatable procedures surface only in its domain bundle
  Given a published domain containing a procedure snippet that carries an activation_trigger
  And that domain's activatable procedures are present in the merged deploy index
  When the deploy inflates the domain's domain-baseline-bundle.md and renders global and project agent configurations
  Then the domain-baseline-bundle.md carries an "## Activatable Procedures" section auto-including that procedure with its description and activation trigger
  And the global agent config's "## Activatable Procedures" section lists only domain-agnostic general-scope triggered procedures
  And the domain-resident procedure appears in no global or project catalog
  And every published domain's required activation trigger from its owner's project configuration renders enriched on its Published Domains line in the global output, which is the only output carrying that section
  And no such procedure is dropped from its domain bundle
```


#### UC-ARD12: Deleted command sources are retracted from the shared commands directory

```
Scenario: UC-ARD12 A removed command source disappears from ~/.teleclaude/commands/ on the next deploy
  Given a command previously deployed to ~/.teleclaude/commands/ by a deploy-mode sync
  When its source artifact is deleted and a deploy-mode sync runs again from the same source scope
  Then the deployed copy is removed from ~/.teleclaude/commands/
  And commands owned by other source scopes remain in ~/.teleclaude/commands/
  And a destination file with no ownership record is preserved
```


<!-- planned:command-migration-to-singular-telec-skill -->

#### UC-ARD10: TeleClaude command corpus is reached only through the composed loader

```
Scenario: UC-ARD10 Command deployment separates the corpus from runtime artifacts
  Given TeleClaude command artifacts are present under agents/commands/
  When sync runs in deploy mode
  Then the command documents are deployed to ~/.teleclaude/commands/
  And no per-agent runtime receives any command artifact for them
  And `telec sessions run --command <name>` dispatches a new session whose startup message is the composed loader for the selected document
  And machine-emitted procedure loads read the same corpus documents in an already-running session
```

#### UC-ARD14: Legacy Gemini runtime locations receive nothing

```
Scenario: UC-ARD14 Antigravity is served at its documented layout only
  Given the Antigravity CLI is an enabled runtime
  When sync runs in deploy mode
  Then Antigravity runtime artifacts deploy under ~/.gemini/antigravity-cli/
  And no artifact is written to ~/.gemini/commands/, ~/.gemini/skills/, or ~/.gemini/agents/
```

<!-- /planned:command-migration-to-singular-telec-skill -->

<!-- planned:agent-artifact-source-layout -->

#### UC-ARD15: A repository's project-scoped artifact sources are delivered to that project's runtimes

```
Scenario: UC-ARD15 A repository's project-scoped artifact sources are delivered to that project's runtimes
  Given a repository carries commands and skills under agents/project/
  And sync is invoked in deploy mode
  When the local phase deploys
  Then each artifact is offered to an agent session started in that project
  And every agent CLI that project is configured to use is served
  And both artifact kinds are served
```

#### UC-ARD20: A project carrying no artifact sources is unaffected

```
Scenario: UC-ARD20 A project carrying no artifact sources is unaffected
  Given a repository carries no agents/ sources of its own
  And sync is invoked in deploy mode
  When the local phase runs
  Then sessions started in that project are offered exactly what they were offered before
  And the repository is not required to carry an artifact-source directory
```

#### UC-ARD21: Authored sources and generated output never share a location

```
Scenario: UC-ARD21 Authored sources and generated output never share a location
  Given a repository carries agent artifacts under agents/
  And sync is invoked in deploy mode
  When the local phase deploys
  Then no directory serves as both an authored source root and a delivery location
  And a file placed under .agents/ is never read as an authored source
  And an author can tell from a file's location alone whether they wrote it or the platform generated it
```

#### UC-ARD23: Global commands are partitioned by published domain and gated by ownership

```
Scenario: UC-ARD23 Global commands are partitioned by published domain and gated by ownership
  Given a repository declares the domains it publishes
  And it carries commands under agents/global/commands/<domain>/ for one of those domains
  When sync runs in deploy mode
  Then those commands deploy to the global corpus under that domain
  And a command under a domain the repository does not publish is refused with a message naming the file and the domain
  And general commands and global skills from a repository that is not the mother are refused the same way
```

#### UC-ARD24: A global command is invoked by its explicit domain-namespaced name

```
Scenario: UC-ARD24 A global command is invoked by its explicit domain-namespaced name
  Given a command deployed to the global corpus under a domain
  When a session or the lifecycle machinery names that command
  Then the name carries the domain as its first segment
  And two domains may each carry a command of the same bare name without collision
```

<!-- /planned:agent-artifact-source-layout -->

<!-- planned:tier-command-corpus -->

#### UC-ARD25: Every tier root carries its own expanded command corpus

```
Scenario: UC-ARD25 Every tier root carries its own expanded command corpus
  Given a project, a company home, or a person home carries commands under its agents/ input
  When sync runs in deploy mode
  Then each command's expanded document exists exactly once, under that root's .teleclaude/commands/
  And no per-CLI directory at that root receives a copy of it
  And a document reference to that path resolves for an agent reading it in a session rooted there
```

#### UC-ARD26: A bare command name resolves through the session's context

```
Scenario: UC-ARD26 A bare command name resolves through the session's context
  Given a session rooted in a project that declares an owning company
  When it is dispatched a command by bare name
  Then the loader resolves it from the project's corpus, then the owning company's, then the invoking person's workspace corpus, then the global corpus
  And the nearest scope that carries the name wins
  And a tier-local command named after a published domain is refused at sync as a collision
```

<!-- /planned:tier-command-corpus -->

<!-- planned:cross-tier-native-emission -->

#### UC-ARD16: Local-phase delivery is contained to the project that owns the source

```
Scenario: UC-ARD16 Local-phase delivery is contained to the project that owns the source
  Given a repository carries agent artifacts under agents/project/
  And sync is invoked in deploy mode
  When the local phase deploys
  Then no artifact from that source is written into a user-home runtime directory
  And no artifact from that source is written into a machine-global shared directory
  And an agent session started in a different project is not offered those artifacts
```

#### UC-ARD17: Artifacts a project previously published globally are retracted

```
Scenario: UC-ARD17 Artifacts a project previously published globally are retracted
  Given an earlier sync published a project's own artifacts into machine-global runtime locations
  And sync is invoked in deploy mode
  When the local phase deploys
  Then the copies attributable to that project's source scope are removed from those machine-global locations
  And artifacts owned by other source scopes remain
  And a file with no ownership record is preserved
```

#### UC-ARD18: A nearer-scope artifact never displaces a wider-scope artifact of the same name

```
Scenario: UC-ARD18 A nearer-scope artifact never displaces a wider-scope artifact of the same name
  Given a global artifact and a project-local artifact carry the same name
  And sync is invoked in deploy mode from the project carrying the local one
  When the local phase deploys
  Then the global artifact remains unchanged in the location the global phase wrote it
  And the project-local artifact is the one offered to sessions in that project
  And the shadowing is reported to the author
```

#### UC-ARD22: A runtime reading the open convention is served at that location

```
Scenario: UC-ARD22 A runtime reading the open convention is served at that location
  Given a project is configured to use an agent runtime that reads the open project-local convention
  And that project carries skills under its agents/ input
  When the local phase deploys
  Then that runtime's skills are delivered to .agents/skills/ in the project
  And a runtime that reads its own project-local location is served there instead
  And neither location is read back as an authored source
```

#### UC-ARD27: Company-tier skills reach sessions in the company's projects

```
Scenario: UC-ARD27 Company-tier skills reach sessions in the company's projects
  Given a company home carries a skill under its agents/ input
  And a registered project declares that company as its owner
  When sync runs in deploy mode
  Then the skill is materialized into that project's native CLI directories
  And a session in a project owned by a different company is not offered it
  And removing the skill from the company home retracts it from every owned project on the next sync
```

#### UC-ARD28: Person-tier artifacts reach only that person's workspace

```
Scenario: UC-ARD28 Person-tier artifacts reach only that person's workspace
  Given a person home carries a skill under its agents/ input
  When sync runs in deploy mode
  Then the skill is offered to sessions rooted in that person's workspace
  And a session that person runs in a project is not offered it
```

<!-- /planned:cross-tier-native-emission -->

<!-- planned:fleet-artifact-sync -->

#### UC-ARD29: Sync reconciles every registered root regardless of where it runs

```
Scenario: UC-ARD29 Sync reconciles every registered root regardless of where it runs
  Given registered projects and company and person homes carry authored docs/ and agents/
  When sync is invoked in deploy mode from any directory
  Then every registered root is built into its outputs in that one run
  And the result is identical whichever directory the invocation started in
  And no directory outside the registered set is searched
```

#### UC-ARD30: A reference validates against its source, never against the deployed tree

```
Scenario: UC-ARD30 A reference validates against its source, never against the deployed tree
  Given an artifact references a document by its deployed path
  And the referenced document exists in its owner's source tree
  When validation runs
  Then the reference is accepted whether or not the deployed tree currently carries it
  And a reference whose target exists in no owner's source tree is refused with a message naming the file and the reference
```

<!-- /planned:fleet-artifact-sync -->

### Cross-context references

- **agent_runtime** — each agent CLI reads its `~/.<agent>/` tree at
  runtime. The deployed directories are the publish/consume boundary
  between Context (publisher) and agent_runtime (consumer).
- **config** — supplies the project root, the Mother project resolution used
  by the agent-artifact publishing gate, and each project's `business.publishes`
  declarations used to compose the docs tree and derive the valid-domain set.

## Known caveats

<!-- planned-change:command-migration-to-singular-telec-skill -->

- Codex commands routing to `~/.teleclaude/commands/` (rather than
  `~/.codex/commands/`) is deliberate cross-project sharing. It
  surprises operators who expect symmetry with `~/.claude/` and
  `~/.gemini/`. The decision is intentional, not a bug.

<!-- change:command-migration-to-singular-telec-skill -->

- TeleClaude command artifacts route to `~/.teleclaude/commands/` rather
  than per-agent native command directories. This is deliberate cross-project
  sharing. The composed loader message is the only runtime entrypoint:
  `telec sessions run` preloads it into a new session, and machine-emitted
  procedure loads carry it into a running one.

<!-- /planned-change:command-migration-to-singular-telec-skill -->

- Documentation links are read-only by convention. Each per-domain directory
  symlink resolves onto its owning publisher's live source directory, so a stray
  edit through it mutates source; agents treat deployed docs as read-only.

<!-- planned-change:agent-artifact-source-layout -->

- Global skill publication is declared structurally, not through a capability
  toggle. The registered project set is the discovery boundary; within each root,
  direct `agents/skills/<name>/` folders are contributions and catalog-level files
  are Mother-owned control-plane content.

<!-- change:agent-artifact-source-layout -->

- Global skill publication is mother-curated. A project wanting a skill
  machine-wide contributes it to the mother repository; the catalog is a
  curation surface, not a merge of every registered root.

<!-- /planned-change:agent-artifact-source-layout -->
- Documentation is authored only on `main`. A deploy-mode sync is refused from a
  slug worktree, so a worktree branch's docs are never deployed; the deploy
  sources the Mother's canonical checkout. The main checkout and the integration
  worktree are the only contexts that deploy the doc layer.

- The distribution step is always fatal: a non-zero distribution exit propagates
  and fails the sync (there is no suppress-on-warn mode). A split domain
  ownership declaration and a bundle-inflation failure both abort the deploy this
  way. The docs watcher, which must not block, catches that failure at its own
  subprocess boundary instead.
- The deployed `index.yaml` is the union of every owner's source per-domain
  `index.yaml`; each source index already carries `~/.teleclaude` paths, so the
  merge is a union of entries with no path rewrite. With one owner per domain the
  union has no cross-owner id collision to resolve. Consumers see identical paths
  from any owner's working tree and the deployed view — there is no deploy-time
  index divergence.
