---
description: 'Two-phase deployment of transpiled artifacts to per-agent home dirs, with Codex commands routed to a shared TeleClaude dir and global docs composed as a per-domain symlink with exactly one owning publisher per domain.'
visibility: 'public'
---

# Agent Runtime Deployment — Spec

## Required reads

- @docs/local/spec/domain/context.md

## What it is

The distribution phase writes the outputs each agent CLI reads at runtime.
Recorded-commit publication invokes its internal deployment entry after
validating the committed source. Direct invocation builds for inspection only.
Deployment runs two phases:

1. **Global phase** — sources from `agents/global/` (global skills from the
   mother alone) are built under a transient distribution directory and
   deployed to the global consumers: the per-agent user-home roots and the
   global skill catalog. A repository carrying global artifacts outside its
   declared reach fails validation rather than being silently skipped.

2. **Local phase** — sources from `agents/local/` (any repository) are
   built under a transient distribution directory and then deployed to that
   project's own runtime locations. `.agents/` is one of those delivery
   locations, never an input.

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

No command artifact exists and no command corpus is deployed. What a session is
assigned is a published procedure, reached exclusively through the loader
message TeleClaude composes at procedure entry, which instructs the session to
retrieve that procedure's instructions from the publication. How a procedure is
resolved and its loader composed is the agent runtime's contract
(`local/projects/teleclaude/spec/feature/agent_runtime/procedure-entry`). A
deployed `~/.teleclaude/commands/` directory left by an earlier publication is
retracted by the owning repository's next publication as an obsolete owned
destination.

Global skills compose to `~/.teleclaude/skills/` and are discovered through the
catalog the master points at; they reach no runtime home. Tier-local skills — the
skill packages a repository authors for its own sessions — materialize into the
native CLI skill directories at their root, because being preloaded is their
purpose. Subagent definitions are
not an artifact class. Beyond tier-local skills, the entrypoint master is the
only per-agent output, written where each CLI reads it unprompted — for the Antigravity CLI (`agy`) that is the configured
`context.fileName` (`AGENTS.md`) under `~/.gemini/antigravity-cli/`. The
legacy Node Gemini CLI layout — `~/.gemini/commands/`, `~/.gemini/skills/`,
`~/.gemini/agents/`, and `~/.gemini/GEMINI.md` — is obsolete and is no longer
provisioned. Content in any runtime home that this pipeline did not produce is
left untouched.

The global documentation tree at `~/.teleclaude/docs/` is a complete materialized
snapshot. Publication stages the deployed generation, replaces only the
triggering repository's owned contribution from its recorded commit, rebuilds
the merged index and bundles, and atomically replaces the deployed root. Other
repositories' contributions remain at their previously deployed revisions.
The valid domains are the union of registered projects' `business.publishes`;
TeleClaude holds no central domain allow-list.
No domain is implicit: `general` enters the valid set, is materialized, and has
its bundle generated only because a registered publisher declares it. Where no
registered publisher declares a domain, identifiers and references naming it
belong to no published domain.

The registered-publisher set is maintained automatically: committed-state
publication from a project declaring `business.publishes` registers that
project's durable root. Split detection evaluates every registered domain
publisher, so a newly registered publisher participates in the one-owner-per-domain
hard block for documentation and domain-partitioned global commands.

Sync-time split detection runs before composition: if more than one registered
project declares the same domain in `business.publishes`, the deploy
HARD-BLOCKS (exits non-zero, composes nothing) with `split domain ownership:
<domain> claimed by <A> and <B>`. The single declaring project supplies the
materialized domain source. This runtime check is the cross-publisher integrity
rule: a domain has exactly one owning publisher.

The deploy writes the merged `index.yaml` at the root — the union of every
owner's per-domain global index. Because no two owners share a domain, the union
carries no cross-owner id collision to resolve. The single filesystem root
`~/.teleclaude/docs` is preserved so the three readers that resolve global docs —
the SessionStart hook, `telec docs`, and the index build — read one root
unchanged.

For each published domain, `general` included, the deploy inflates the
domain's `baseline.md` and its `baseline-progressive.md` sibling into
`<domain>/bundle.md` inside the staged generation. The general bundle is the
global agent configuration's baseline, named by the global master as a Required
Read. The bundle publishes with that generation and is single-source because
split detection permits one owner per domain. Documentation composition and bundle
generation complete before agent artifacts are transpiled, so a procedure that
needs the generated bundle names it as an explicit Required Read. The transpiler
expands that bundle into the consuming artifact; SessionStart does not select or
inject command-domain baseline context.

Global third-party docs are a Mother-owned contribution to the same staged
generation. The mother's publication replaces the generation's `third-party/`
root with the committed `docs/third-party/` of its recorded commit and writes
that root's global third-party index, which names the deployed `third-party/`
root as the location of its documents. Another repository's publication
carries the root forward unchanged. Readers resolve global third-party docs
from the deployed `third-party/` root only, never from a release's or a
checkout's source tree, so `~/.teleclaude/docs/third-party/` is where
`general/spec/third-party-docs` places them.

When the distribution step is invoked directly in no-deploy mode, agent
artifacts are emitted to `project_root/dist/global` and
`project_root/dist/local` (not transient dirs), no copies are made to
`~/.<agent>/`, and documentation deployment is skipped. This direct
no-deploy mode is for developers/CI inspecting build output.

## Canonical fields

Deployment is scoped to projects subscribing the `agents` capability
(`local/projects/teleclaude/spec/feature/config/project-capability-manifest`). For a project that
does not subscribe it, neither transpilation phase nor artifact deployment runs;
documentation publication is governed independently by the `docs` capability.

The behavioral contract is `UC-CFG-CAP-18` in
`local/projects/teleclaude/spec/feature/config/project-capability-manifest`; this spec references that scenario
rather than restating it.

### Use cases

```
Scenario: UC-ARD1 Mother project full sync with deploy
  Given the project is the Mother project
  And sync is invoked in deploy mode
  When the distribution pipeline runs
  Then the entrypoint master deploys to each enabled runtime's home
  And global skill packages compose to ~/.teleclaude/skills/
  And no global skill or subagent artifact is written into any runtime home
  And AGENTS.override.md is written to the project root for Codex override detection
  And docs/global/ is composed per domain into the ~/.teleclaude/docs/ root
```

```
Scenario: UC-ARD2 Non-mother project sync skips global agent-artifact phase
  Given the project is not the Mother project
  And sync is invoked in deploy mode
  When the distribution pipeline runs
  Then the global phase produces no agent-home artifact writes
  And the local phase materializes the repository's own skill packages into the project-root CLI skill directories
  And the local phase writes no subagent definition into any runtime home
  And each domain the project owns in business.publishes is materialized into the deployed documentation snapshot
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
  Then ~/.teleclaude/docs remains a complete deployed snapshot throughout publication
  And each published domain, general included, is materialized from its single owning source
  And ~/.teleclaude/docs/index.yaml is the union of every owners global index
  And each published domain baseline is generated inside the same staged snapshot
  And a snippet removed from a source domain is absent from the next deployed snapshot
```

```
Scenario: UC-ARD5 Distribution invoked directly builds and never deploys
  Given the distribution step is invoked directly rather than through recorded-commit publication
  When the distribution pipeline runs
  Then agent artifacts are emitted under project_root/dist/global and project_root/dist/local
  And no transient distribution dirs are used
  And no writes occur to ~/.claude/, ~/.gemini/, ~/.codex/
  And documentation deployment is NOT performed
  And the direct entry exposes no mode that writes a runtime destination
  And the dist/ output is left in place for inspection
```

#### UC-ARD13: A generated domain bundle resolves as an explicit Required Read

```
Scenario: UC-ARD13 A generated domain bundle resolves as an explicit Required Read
  Given a procedure names ~/.teleclaude/docs/<domain>/bundle.md as a Required Read
  And the domain has exactly one registered publisher
  When deploy mode runs
  Then documentation composition generates the current domain bundle before agent-artifact transpilation
  And the transpiler expands the generated bundle into each consuming artifact exactly once
  And validation accepts the canonical generated-bundle path without treating it as an authored snippet
  And a generation or resolution failure aborts before previously deployed agent artifacts are replaced
```

#### UC-ARD39: A generated bundle reference resolves to the generation, not to a publisher source

```
Scenario: UC-ARD39 A generated bundle reference resolves to the generation
  Given a procedure names ~/.teleclaude/docs/<domain>/bundle.md as a Required Read
  And the owning publisher's own docs tree holds no file at that domain's bundle path
  When agent artifacts are transpiled in deploy mode
  Then the reference resolves to the bundle inside the deployed generation
  And the consuming artifact carries the bundle content this run generated
  And a same-named file left behind in a publisher source tree is never read in its place
```

```
Scenario: UC-ARD6 A procedure carries its generated domain bundle explicitly
  Given a procedure requires a generated domain baseline bundle
  And its Required reads name ~/.teleclaude/docs/<domain>/bundle.md
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

#### UC-ARD9: Published-domain activatable procedures are scoped to global agent output

```
Scenario: UC-ARD9 A published domain's activatable procedures surface only in its domain bundle
  Given a published domain containing a procedure snippet that carries an activation_trigger
  And that domain's activatable procedures are present in the merged deploy index
  When the deploy inflates the domain's bundle.md and renders global and project agent configurations
  Then the bundle.md carries an "## Activatable Procedures" section auto-including that procedure with its description and activation trigger
  And the procedure appears in no project catalog
  And the global agent config carries it only when its domain is general, through the general bundle the global master inlines, and appends no activatable catalog of its own
  And every published domain whose bundle the global output does not inline renders the activation trigger its owner declares in business.publishes enriched on its Published Domains line in the global output, which is the only output carrying that section
  And no such procedure is dropped from its domain bundle
```

#### UC-ARD12: Deployed command documents are retracted

```
Scenario: UC-ARD12 Every command document a repository deployed disappears from ~/.teleclaude/commands/ on its next deploy
  Given command documents previously deployed to ~/.teleclaude/commands/ by a deploy-mode sync under a repository's ownership
  When a deploy-mode sync runs again for that repository
  Then every deployed copy that repository owned is removed from ~/.teleclaude/commands/
  And a destination file with no ownership record is preserved
```

#### UC-ARD40: A retiring command stays deployed until its delivery folds

```
Scenario: UC-ARD40 A session can still load a retiring command until its delivery folds
  Given a command source with an empty retirement companion beside it
  When a deploy-mode sync runs
  Then an agent session loading that command from the corpus receives it unchanged
  And an agent session finds no command named after the companion
```

#### UC-ARD10: Command documents deploy to the corpus and to no runtime home

#### UC-ARD14: Legacy Gemini runtime locations receive nothing

```
Scenario: UC-ARD14 Antigravity is served at its documented layout only
  Given the Antigravity CLI is an enabled runtime
  When sync runs in deploy mode
  Then Antigravity runtime artifacts deploy under ~/.gemini/antigravity-cli/
  And no artifact is written to ~/.gemini/commands/, ~/.gemini/skills/, or ~/.gemini/agents/
```

#### UC-ARD34: A retired native destination is retracted under the ownership record

```gherkin
Scenario: UC-ARD34 Retraction removes what the pipeline deployed and keeps what it did not
  Given a runtime command directory holds the copies this pipeline deployed for a source scope
  And that directory also holds a file the pipeline never deployed
  When sync runs in deploy mode
  Then every copy the scope's ownership record names is removed from that directory
  And the file carrying no ownership record is left in place
  And the command corpus is unaffected
  And a second deploy-mode sync removes nothing further
```

#### UC-ARD15: A repository's project-scoped skills are delivered to that project's runtimes and its project commands are validated

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

#### UC-ARD24: A global command is deployed under its domain in the corpus

#### UC-ARD37: One repository's deploy never retracts another repository's global commands

#### UC-ARD38: Partitioning the corpus retracts nothing a publisher still carries

#### UC-ARD32: Every artifact source path is classified by one registry boundary

```
Scenario: UC-ARD32 Every artifact source path is classified by one registry boundary
  Given the artifact-source registry declares non-overlapping exact-file, uniform-tree, and immediate-package-directory boundaries with their kind, tier, reach, and authorship
  And the global-skill catalog master matches an authored exact-file boundary
  And each sibling skill package directory matches an incorporated-package boundary
  When artifact validation, global-skill discovery, deployment, checkpoint scope, onboarding inference, or commit review routing resolves a source path
  Then each receives the same single matched registry record
  And no consumer carries a local exception for the catalog master or package bodies
  And a path matching no boundary, more than one boundary, or a record with no explicit disposition fails the run rather than being skipped
```

#### UC-ARD35: A participating tier's published half is materialized into the deployed snapshot

```
Given a company or person tier whose declaration records participation in the documentation surface
And that tier's home holds authored documentation sources in docs/global and docs/local
When committed-state publication activates the platform home's recorded source
Then that tier's docs/global sources are copied into the staged generation under companies/<slug>/ or people/<slug>/
And the merged index carries every entry of that tier's published catalog under its qualified identity
And the tier's published catalog is deployed beside its material, whether or not it has entries
And the staged generation replaces the deployed root atomically, tier material included
And discovery of the published half is served from the deployed corpus, never from the tier's authoring home
And retrieving a published tier snippet returns its published body after the source publication built it from is gone
And nothing under the tier's docs/local enters the staged generation or the merged index
```

#### UC-ARD36: An undeclared tier-shaped folder publishes nothing

```
Given the platform home's recorded source contains one declared company or person tier
And an undeclared sibling folder has the same documentation layout
And both hold authored documentation sources
When committed-state publication activates that recorded source
Then the declared tier's material enters the staged generation and merged index
And nothing from the undeclared sibling enters either output
```

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
  Given a repository carries agent artifacts under agents/local/
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

#### UC-ARD31: A saved source deploys nothing; its commit deploys it

```gherkin
Given an agent has saved a documentation or agent-artifact source in a registered project
And that change is not yet committed
When the agent reads the deployed tree for that project
Then the deployed tree still carries the content of the previous commit
When the agent commits that change
Then commit-boundary maintenance records that the committed range was published
And the agent reads the committed content from the deployed tree
```

### Cross-context references

- **agent_runtime** — each agent CLI reads its `~/.<agent>/` tree at
  runtime. The deployed directories are the publish/consume boundary
  between Context (publisher) and agent_runtime (consumer).
- **config** — supplies the project root, the Mother project resolution used
  by the agent-artifact publishing gate, and each project's `business.publishes`
  declarations used to compose the docs tree and derive the valid-domain set.

## Known caveats

- No command artifact exists and no command corpus is deployed: a session reaches
  an assigned procedure only through its published documentation, under
  `local/projects/teleclaude/spec/feature/agent_runtime/procedure-entry`.

- Deployed documentation is read-only. It is a materialized snapshot; authored
  documentation changes only in its owning source tree and becomes visible after
  a successful synchronization publishes the next snapshot.

- Global skill publication is mother-curated. A project wanting a skill
  machine-wide contributes it to the mother repository; the catalog is a
  curation surface, not a merge of every registered root.

- Documentation is authored only on `main`. Publication reads the recorded
  canonical commit, so a slug worktree's uncommitted or branch-only documentation
  never enters the deployed generation.

- A non-zero distribution exit fails the publication action. A split domain
  ownership declaration or bundle-inflation failure aborts deployment, and
  maintenance records the failure against the original committed range for replay.
  The commit that passed validation remains recorded.
- The deployed `index.yaml` is the union of every owner's source per-domain
  `index.yaml`; each source index already carries `~/.teleclaude` paths, so the
  merge is a union of entries with no path rewrite. With one owner per domain the
  union has no cross-owner id collision to resolve. Consumers see identical paths
  from any owner's working tree and the deployed view — there is no deploy-time
  index divergence.
