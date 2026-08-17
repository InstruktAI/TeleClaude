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


1. **Global phase** — sources from `agents/` (Mother project only) are
   built under a transient distribution directory and then deployed
   to per-agent user-home roots: `~/.claude/`, `~/.gemini/`, `~/.codex/`.
   The publishing gate ensures the global agent-artifact source list is
   only populated on the Mother project. Global documentation, in contrast,
   is contributed by every project for the domains it publishes (see below).
2. **Local phase** — sources from `.agents/` (any project) are built
   under a transient distribution directory and then deployed to the
   project root.

Global skill publication is a separate composed surface. Every registered
project contributes each direct `agents/skills/<name>/` folder; no configuration
capability is required because folder existence is the declaration. Sync
materializes the contributed packages under `~/.teleclaude/skills/` and the
Mother project alone supplies the catalog `AGENTS.master.md`. Side-project
catalog masters are not parsed. After the skill links exist, the Mother-owned
catalog master runs through the normal renderer — including `@exec` — and its
generated `AGENTS.md` is written into the deployed catalog. `AGENTS.global.md`
contains only a plain-text discovery pointer to that index, never an `@` ref,
so the skill catalog stays lazy rather than being preloaded.

<!-- planned-change:command-migration-to-singular-telec-skill -->

Codex commands are an exception: they route to
`~/.teleclaude/commands/` (NOT `~/.codex/commands/`) so commands are
reusable across projects.

<!-- change:command-migration-to-singular-telec-skill -->

TeleClaude command artifacts are an exception to per-agent command
deployment: command documents route to `~/.teleclaude/commands/` from the
global phase alone, while the per-agent runtime receives the singular
TeleClaude command skill. The local phase contributes no command documents —
a project cannot author commands of its own, and the attempt is refused. The shared command corpus is reusable
across projects and is not emitted as one native command file per target
agent. No target receives native per-command artifacts.

Skills deploy on two distinct surfaces, and the distinction is what makes the
command skill reachable:

- **Infrastructure skills** are Mother-owned and mandatory. They deploy to every
  enabled agent's per-agent runtime skills directory. The singular TeleClaude
  command skill is an infrastructure skill; without this surface it would reach
  only the lazy catalog and no runtime would load it.
- **Catalog skills** are contributed by any registered project, composed to
  `~/.teleclaude/skills/`, and discovered lazily through the catalog index. They
  are never force-deployed into a per-agent runtime.

Per-agent runtime destinations follow each CLI's documented layout. For the
Antigravity CLI (`agy`) that is `~/.gemini/antigravity-cli/skills/` for the
user-global scope and `.agents/skills/` for the workspace scope; `agy` has no
custom-commands directory, and its instruction files resolve through the
configured `context.fileName` (`AGENTS.md`) rather than a global master. The
legacy Node Gemini CLI layout — `~/.gemini/commands/`, `~/.gemini/skills/`,
`~/.gemini/agents/`, and `~/.gemini/GEMINI.md` — is obsolete and is no longer
provisioned.

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

The registered-publisher set is maintained automatically: a deploy-mode
`telec sync` from a project declaring `business.publishes` or containing a
direct `agents/skills/<name>/` folder registers that project's durable root.
The folder is the skill-publication declaration; no separate configuration
capability or registration step exists. Split detection (below) evaluates every
registered domain publisher, so a self-registered publisher participates in the
one-owner-per-domain hard block like any other.

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
  Then global non-command runtime artifacts from agents/ deploy to ~/.claude/, ~/.gemini/, and ~/.codex/
  And local non-command runtime artifacts from .agents/ deploy to the project root
  And TeleClaude command artifacts from agents/ and .agents/ deploy to ~/.teleclaude/commands/
  And the singular TeleClaude command skill deploys to each supported agent's skills directory
  And no TeleClaude command artifact is deployed as a native per-command slash command under ~/.claude/, ~/.gemini/, or ~/.codex/
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
  And the local phase deploys non-command .agents/ runtime artifacts to the project root
  And local TeleClaude command artifacts still route to ~/.teleclaude/commands/
  And the singular TeleClaude command skill deploys to each supported agent's skills directory
  And no local TeleClaude command artifact is deployed as a native per-command slash command under the project-root agent runtime directories
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
  And its @exec directives observe the assembled catalog
  And ~/.teleclaude/skills/AGENTS.md indexes the deployed skills
  And the global agent baseline carries only a plain-text pointer to that index
```

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

#### UC-ARD10: TeleClaude command corpus is invoked through the command skill

```
Scenario: UC-ARD10 Command deployment separates dispatch from same-session loading
  Given TeleClaude command artifacts are present under agents/commands/
  When sync runs in deploy mode
  Then the command documents are deployed to ~/.teleclaude/commands/
  And each supported agent receives the singular TeleClaude command skill in its skills directory
  And same-session command invocation loads the selected document through that skill
  And `telec sessions run --command /<name>` remains the new-session dispatch surface that preloads the selected command into the spawned session
```

#### UC-ARD14: Infrastructure skills reach every runtime; catalog skills stay lazy

```
Scenario: UC-ARD14 The two skill surfaces are deployed distinctly
  Given a Mother-owned infrastructure skill and a project-contributed catalog skill both exist
  When sync runs in deploy mode
  Then the infrastructure skill is deployed to every enabled agent's per-agent runtime skills directory
  And the catalog skill is composed to ~/.teleclaude/skills/ and is not deployed to any per-agent runtime
  And the Antigravity runtime receives its skills under ~/.gemini/antigravity-cli/skills/
  And no artifact is written to ~/.gemini/commands/, ~/.gemini/skills/, or ~/.gemini/agents/
```

<!-- /planned:command-migration-to-singular-telec-skill -->

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
  sharing. The TeleClaude command skill is the runtime entrypoint for
  same-session command loading, while `telec sessions run` remains the
  new-session dispatch entrypoint.

<!-- /planned-change:command-migration-to-singular-telec-skill -->

- Documentation links are read-only by convention. Each per-domain directory
  symlink resolves onto its owning publisher's live source directory, so a stray
  edit through it mutates source; agents treat deployed docs as read-only.

- Global skill publication is declared structurally, not through a capability
  toggle. The registered project set is the discovery boundary; within each root,
  direct `agents/skills/<name>/` folders are contributions and catalog-level files
  are Mother-owned control-plane content.

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
