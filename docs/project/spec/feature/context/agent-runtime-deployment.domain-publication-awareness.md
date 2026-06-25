---
description: "Two-phase deployment of transpiled artifacts to per-agent home dirs, with Codex commands routed to a shared TeleClaude dir and global docs composed from every publisher's docs/global as a per-domain multi-root tree under one filesystem root."
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
`~/.teleclaude/docs/` as a **composed per-domain multi-root tree**. The root is
a real directory whose children are: one symlink per published domain
(`~/.teleclaude/docs/<domain>` → its owning publisher's
`docs/global/<domain>`), a `general/` symlink to the Mother repo's shared
`docs/global/general`, and a merged `index.yaml` unioned from every publisher's
global index. Each published domain resolves to its owning publisher's source
as a live view (no copy, no aggregation), and a domain has exactly one owning
publisher. The single filesystem root `~/.teleclaude/docs` is preserved so the
three readers that resolve global docs — the SessionStart hook, `telec docs`,
and the index build — read one root unchanged.

For each source `docs/global/<domain>/baseline.md` the deploy inflates the
domain baseline and writes it as a generated, gitignored file beside its
manifest at `docs/global/<domain>/domain-baseline.md`, visible through the
per-domain symlink at `~/.teleclaude/docs/<domain>/domain-baseline.md`. These
generated baselines are excluded from snippet iteration and validation, so they
are never treated as authored snippets. The SessionStart hook reads that file to
inject the domain's process-enforcement baseline. Global third-party docs are
read from the mother repo source (`docs/third-party/`), not from under the docs
tree.

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
  And docs/global/ is exposed as a composed per-domain multi-root tree at ~/.teleclaude/docs/
```

```
Scenario: UC-ARD2 Non-mother project sync skips global agent-artifact phase
  Given the project is not the Mother project
  And sync is invoked in deploy mode
  When the distribution pipeline runs
  Then the global phase produces no agent-home artifact writes
  And the local phase deploys .agents/ to the project root
  And Codex commands still route to ~/.teleclaude/commands/
  And the project's docs/global/<domain> for each domain it publishes is composed into ~/.teleclaude/docs/
```

```
Scenario: UC-ARD3 Sync from a worktree uses worktree docs
  Given sync runs from a git worktree of the Mother project
  When the canonical-root resolver identifies the canonical root
  Then the docs source is the current worktree checkout
  And the Mother-owned domains deployed reflect the worktree's branch through their per-domain links, not main
```

```
Scenario: UC-ARD4 Sync composes the per-domain multi-root docs tree
  Given two publishers, each declaring the domains it owns
  And each publisher source domain docs/global/<domain>/ has a baseline.md
  When the documentation deployment step runs
  Then any stale real or symlinked ~/.teleclaude/docs from an older deploy is replaced
  And ~/.teleclaude/docs is a real directory containing one symlink per published domain to its owning publisher's docs/global/<domain>
  And ~/.teleclaude/docs/general resolves to the Mother repo's docs/global/general
  And ~/.teleclaude/docs/index.yaml is the union of every publisher's global index
  And the inflated domain baseline is written to each owning publisher's docs/global/<domain>/domain-baseline.md
  And that generated baseline is gitignored and excluded from snippet iteration and validation
  And a subfolder added to a source domain afterward resolves through its per-domain link without a re-deploy
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
Scenario: UC-ARD6 SessionStart injects the generated domain baseline
  Given a session whose command resolves to a domain with a generated baseline
  When the SessionStart hook builds additional context
  Then it reads ~/.teleclaude/docs/<domain>/domain-baseline.md
  And injects the inflated domain process-enforcement baseline before the first user message
```

```
Scenario: UC-ARD7 SessionStart surfaces a missing domain baseline
  Given a session whose command resolves to a domain whose generated baseline is absent
  When the SessionStart hook builds additional context
  Then it surfaces a visible warning naming the missing ~/.teleclaude/docs/<domain>/domain-baseline.md
  And the mandatory baseline is never silently dropped
```

### Cross-context references

- **agent_runtime** — each agent CLI reads its `~/.<agent>/` tree at
  runtime. The deployed directories are the publish/consume boundary
  between Context (publisher) and agent_runtime (consumer).
- **config** — supplies the project root, the Mother project resolution used
  by the agent-artifact publishing gate, and each project's published-domain
  declarations used to compose the docs tree.

## Known caveats

- Codex commands routing to `~/.teleclaude/commands/` (rather than
  `~/.codex/commands/`) is deliberate cross-project sharing. It
  surprises operators who expect symmetry with `~/.claude/` and
  `~/.gemini/`. The decision is intentional, not a bug.
- Documentation links are read-only by convention. Each per-domain symlink
  resolves onto its owning publisher's live source tree, so a stray edit
  through it mutates source; agents treat deployed docs as read-only.
- Worktree-aware docs sourcing prevents the easy bug of "synced from a
  worktree but deployed main-branch docs". A worktree whose `docs/` is
  missing, however, falls back silently rather than erroring.
- The distribution step is always fatal: a non-zero distribution exit propagates
  and fails the sync (there is no suppress-on-warn mode). The docs watcher, which
  must not block, catches that failure at its own subprocess boundary instead.
- The deployed `index.yaml` is a merged union of every publisher's source
  `index.yaml`; each source index already carries `~/.teleclaude` paths, so the
  merge is a union of entries with no path rewrite. Consumers see identical
  paths from any publisher's working tree and the deployed view — there is no
  deploy-time index divergence.
