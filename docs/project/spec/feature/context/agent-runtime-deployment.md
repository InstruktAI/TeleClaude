---
description: 'Two-phase deployment of transpiled artifacts to per-agent home dirs, with Codex commands routed to a shared TeleClaude dir and docs atomically symlinked.'
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
   The publishing gate ensures the global source list is only populated
   on the Mother project.
2. **Local phase** — sources from `.agents/` (any project) are built
   under a transient distribution directory and then deployed to the
   project root. Codex commands are an exception: they route to
   `~/.teleclaude/commands/` (NOT `~/.codex/commands/`) so commands are
   reusable across projects.

After both phases, the documentation tree is atomically symlinked from
source into `~/.teleclaude/docs/`, with the deployed `index.yaml`
rewritten so consumers see deployment-relative paths.

The deployed `~/.teleclaude/docs/` is a real directory holding the rewritten
`index.yaml`, the `third-party/` tree, and one **whole-folder symlink per
domain** (`~/.teleclaude/docs/<domain>` → `docs/global/<domain>`). The deploy
root stays a real directory because the deployed `index.yaml` is rewritten in
place; a symlinked root is refused. A per-domain symlink is a live view —
every current and later source child resolves through it, so a domain can
never be partially deployed. For each source `docs/global/<domain>/baseline.md`
the deploy inflates the domain baseline and writes it as a generated artifact
in the deployed root at `~/.teleclaude/docs/_baselines/<domain>.md` — never
into the docs Source tree, so "Source lives in git only" holds. The
SessionStart hook reads that generated file to inject the domain's
process-enforcement baseline; the source `baseline.md` manifest exposed
through the symlink is dormant and never consumed as the baseline.

When the distribution step is invoked directly in no-deploy mode, agent
artifacts are emitted to `project_root/dist/global` and
`project_root/dist/local` (not transient dirs), no copies are made to
`~/.<agent>/`, and documentation deployment is skipped. This direct
no-deploy mode is for developers/CI inspecting build output, not for
`telec sync`.

## Canonical fields

### Use cases

```
Scenario: Mother project full sync with deploy
  Given the project is the Mother project
  And sync is invoked in deploy mode
  When the distribution pipeline runs
  Then global sources from agents/ deploy to ~/.claude/, ~/.gemini/, and ~/.codex/
  And local sources from .agents/ deploy to the project root
  And Codex commands deploy to ~/.teleclaude/commands/
  And AGENTS.override.md is written to the project root for Codex override detection
  And docs/global/ is symlinked into ~/.teleclaude/docs/
```

```
Scenario: Non-mother project sync skips global phase
  Given the project is not the Mother project
  And sync is invoked in deploy mode
  When the distribution pipeline runs
  Then the global phase produces no agent-home writes
  And the local phase deploys .agents/ to the project root
  And Codex commands still route to ~/.teleclaude/commands/
```

```
Scenario: Sync from a worktree uses worktree docs
  Given sync runs from a git worktree of the Mother project
  When the canonical-root resolver identifies the canonical root
  Then the docs source is the current worktree checkout
  And docs deployed reflect the worktree's branch, not main
  And the deployed index.yaml is rewritten with the deployment root
```

```
Scenario: Sync repairs a broken docs symlink
  Given ~/.teleclaude/docs/ contains a broken or self-pointing symlink
  When the documentation deployment step runs
  Then the broken link is unlinked
  And a fresh atomic symlink is created to the docs source
  And third-party/ contents are preserved across the deploy
  And the deployed index.yaml is rewritten with the deployment-relative project and snippet roots
```

```
Scenario: Distribution invoked directly in no-deploy mode
  Given the distribution step is invoked directly (not through telec sync) in no-deploy mode
  When the distribution pipeline runs
  Then agent artifacts are emitted under project_root/dist/global and project_root/dist/local
  And no transient distribution dirs are used
  And no writes occur to ~/.claude/, ~/.gemini/, ~/.codex/
  And documentation deployment is NOT performed
  And the dist/ output is left in place for inspection
```

```
Scenario: A domain folder deploys as a live whole-folder symlink with a generated baseline
  Given a source domain docs/global/<domain>/ with a baseline.md and one or more subfolders
  When the documentation deployment step runs
  Then ~/.teleclaude/docs/<domain> is a whole-folder symlink to docs/global/<domain>
  And the inflated domain baseline is written to ~/.teleclaude/docs/_baselines/<domain>.md
  And no file is written under the docs source tree
  And a subfolder added to the source domain afterward resolves through the deployed symlink without a re-deploy
```

### Cross-context references

- **agent_runtime** — each agent CLI reads its `~/.<agent>/` tree at
  runtime. The deployed directories are the publish/consume boundary
  between Context (publisher) and agent_runtime (consumer).
- **config** — supplies the project root and the Mother project
  resolution used by the publishing gate.

## Known caveats

- Codex commands routing to `~/.teleclaude/commands/` (rather than
  `~/.codex/commands/`) is deliberate cross-project sharing. It
  surprises operators who expect symmetry with `~/.claude/` and
  `~/.gemini/`. The decision is intentional, not a bug.
- Documentation symlinks are read-only by convention. Agents that edit
  deployed files are scribbling in scratch that the next sync
  overwrites.
- Worktree-aware docs sourcing prevents the easy bug of "synced from a
  worktree but deployed main-branch docs". A worktree whose `docs/` is
  missing, however, falls back silently rather than erroring.
- The distribution step is always fatal: a non-zero distribution exit propagates
  and fails the sync (there is no suppress-on-warn mode). The docs watcher, which
  must not block, catches that failure at its own subprocess boundary instead.
- The deployed `index.yaml` is rewritten in-place during deployment.
  Consumers reading the working-tree index will see different
  `project_root` values than the deployed one — this is expected, not
  drift.
