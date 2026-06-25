---
description: "Two-phase deployment of transpiled artifacts to per-agent home dirs, with Codex commands routed to a shared TeleClaude dir and global docs composed per file from every publisher's docs/global into one merged filesystem root."
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
   project root. Codex commands are an exception: they route to
   `~/.teleclaude/commands/` (NOT `~/.codex/commands/`) so commands are
   reusable across projects.

After both phases, the global documentation tree is exposed at
`~/.teleclaude/docs/` as a **per-file merge of every publisher's
`docs/global`**. The root is a real directory rebuilt each sync: for every

<!-- planned-change:domains-constant-not-config -->

contributing publisher and every snippet file under a domain it declares in
`business.publishes` (plus the cross-cutting `general/`), the file is linked in
per file

<!-- change:domains-constant-not-config -->

contributing publisher and every snippet file under a `docs/global/<domain>`
directory whose name is a valid platform domain (plus the cross-cutting
`general/`), the file is linked in per file

<!-- /planned-change:domains-constant-not-config -->

(`~/.teleclaude/docs/<rel>` → the publisher's source file). A domain
directory therefore merges files from multiple publishers — there is no domain
ownership; the only cross-publisher constraint is snippet-id uniqueness. Each
file is a live view of its source (no copy). Build-time manifests
(`index.yaml`, `baseline*.md`) are not linked; the deploy writes its own build
outputs as real files: a merged `index.yaml` (the union of every publisher's
global index, deduped by id) and one `domain-baseline-bundle.md` per published
domain. The root is rebuilt from the desired set each sync, so a removed or
renamed snippet leaves no orphan link. The single filesystem root
`~/.teleclaude/docs` is preserved so the three readers that resolve global docs —
the SessionStart hook, `telec docs`, and the index build — read one root
unchanged.

For each published domain the deploy inflates the union of every contributing
publisher's `baseline.md` (and `baseline-progressive.md`) once, deduped, and
writes the result as a real `~/.teleclaude/docs/<domain>/domain-baseline-bundle.md`.
The SessionStart hook reads that bundle to inject the domain's
process-enforcement baseline. Global third-party docs are read from the mother
repo source (`docs/third-party/`), not from under the docs tree.

When the distribution step is invoked directly in no-deploy mode, agent
artifacts are emitted to `project_root/dist/global` and
`project_root/dist/local` (not transient dirs), no copies are made to
`~/.<agent>/`, and documentation deployment is skipped. This direct
no-deploy mode is for developers/CI inspecting build output, not for
`telec sync`.

## Canonical fields

### Use cases

```
Scenario: UC-ARD1 Mother project full sync with deploy
  Given the project is the Mother project
  And sync is invoked in deploy mode
  When the distribution pipeline runs
  Then global sources from agents/ deploy to ~/.claude/, ~/.gemini/, and ~/.codex/
  And local sources from .agents/ deploy to the project root
  And Codex commands deploy to ~/.teleclaude/commands/
  And AGENTS.override.md is written to the project root for Codex override detection
  And docs/global/ is composed per file into the merged ~/.teleclaude/docs/ root
```

```
Scenario: UC-ARD2 Non-mother project sync skips global agent-artifact phase
  Given the project is not the Mother project
  And sync is invoked in deploy mode
  When the distribution pipeline runs
  Then the global phase produces no agent-home artifact writes
  And the local phase deploys .agents/ to the project root
  And Codex commands still route to ~/.teleclaude/commands/
<!-- planned-change:domains-constant-not-config -->
  And the project's docs/global/<domain> files for each domain it publishes are merged into ~/.teleclaude/docs/
<!-- change:domains-constant-not-config -->
  And the project's docs/global/<domain> files for each directory whose name is a valid platform domain are merged into ~/.teleclaude/docs/
<!-- /planned-change:domains-constant-not-config -->
```

```
Scenario: UC-ARD3 Sync from a worktree uses worktree docs
  Given sync runs from a git worktree of the Mother project
  When the canonical-root resolver identifies the canonical root
  Then the docs source is the current worktree checkout
  And the Mother repo's contributed domain files deployed reflect the worktree's branch, not main
```

```
Scenario: UC-ARD4 Sync composes the per-file multi-publisher docs tree
<!-- planned-change:domains-constant-not-config -->
  Given two publishers, each declaring in business.publishes the domains it contributes
<!-- change:domains-constant-not-config -->
  Given two publishers, each contributing docs/global/<domain> folders whose names are valid platform domains
<!-- /planned-change:domains-constant-not-config -->
  And both publishers contribute distinct snippet files to the same domain
  When the documentation deployment step runs
  Then any stale real or symlinked ~/.teleclaude/docs from an older deploy is replaced
  And ~/.teleclaude/docs is a real directory whose snippet files are symlinks to their publisher sources
  And the shared domain directory contains the merged files from both publishers, each resolving to its own source
  And ~/.teleclaude/docs/general resolves to the Mother repo's docs/global/general
  And ~/.teleclaude/docs/index.yaml is the union of every publisher's global index
  And each published domain has a regenerated ~/.teleclaude/docs/<domain>/domain-baseline-bundle.md unioning every contributor's baseline manifest
  And a snippet removed from a source domain leaves no orphan link after the next deploy
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

```
Scenario: UC-ARD6 SessionStart injects the generated domain bundle
  Given a session whose command resolves to a domain with a generated bundle
  When the SessionStart hook builds additional context
  Then it reads ~/.teleclaude/docs/<domain>/domain-baseline-bundle.md
  And injects the inflated domain process-enforcement baseline before the first user message
```

```
Scenario: UC-ARD7 SessionStart surfaces a missing domain bundle
  Given a session whose command resolves to a domain whose generated bundle is absent
  When the SessionStart hook builds additional context
  Then it surfaces a visible warning naming the missing ~/.teleclaude/docs/<domain>/domain-baseline-bundle.md
  And the mandatory baseline is never silently dropped
```

```
Scenario: UC-ARD8 Duplicate snippet id across publishers blocks the deploy
  Given two publishers whose global indexes declare the same snippet id
  When the documentation deployment step merges their indexes
  Then the deploy aborts with a sync-blocking error naming the colliding id and both publishers
  And no merged index is written
```

### Cross-context references

- **agent_runtime** — each agent CLI reads its `~/.<agent>/` tree at
runtime. The deployed directories are the publish/consume boundary
between Context (publisher) and agent_runtime (consumer).
<!-- planned-change:domains-constant-not-config -->
- **config** — supplies the project root, the Mother project resolution used
by the agent-artifact publishing gate, and each project's `business.publishes`
declarations used to compose the docs tree.
<!-- change:domains-constant-not-config -->
- **config** — supplies the project root and the Mother project resolution used
by the agent-artifact publishing gate. Publication is discovered from valid
`docs/global/<domain>/` folder presence, not from project config.
<!-- /planned-change:domains-constant-not-config -->

## Known caveats

- Codex commands routing to `~/.teleclaude/commands/` (rather than
  `~/.codex/commands/`) is deliberate cross-project sharing. It
  surprises operators who expect symmetry with `~/.claude/` and
  `~/.gemini/`. The decision is intentional, not a bug.
- Documentation links are read-only by convention. Each per-file symlink
  resolves onto its contributing publisher's live source file, so a stray edit
  through it mutates source; agents treat deployed docs as read-only.
- Worktree-aware docs sourcing prevents the easy bug of "synced from a
  worktree but deployed main-branch docs". A worktree whose `docs/` is
  missing, however, falls back silently rather than erroring.
- The distribution step is always fatal: a non-zero distribution exit propagates
  and fails the sync (there is no suppress-on-warn mode). A cross-publisher id
  collision and a bundle-inflation failure both abort the deploy this way. The
  docs watcher, which must not block, catches that failure at its own subprocess
  boundary instead.
- The deployed `index.yaml` is a merged union of every publisher's source
  `index.yaml`; each source index already carries `~/.teleclaude` paths, so the
  merge is a union of entries with no path rewrite. Consumers see identical
  paths from any publisher's working tree and the deployed view — there is no
  deploy-time index divergence.
