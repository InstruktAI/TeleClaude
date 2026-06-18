---
description: 'Two-phase deployment of transpiled artifacts to per-agent home dirs, with Codex commands routed to a shared TeleClaude dir and global docs exposed as a single whole-tree symlink.'
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

After both phases, the global documentation tree is exposed at
`~/.teleclaude/docs/` as a single whole-tree symlink to the source
`docs/global/` directory.

`~/.teleclaude/docs` is one symlink (`~/.teleclaude/docs` → `docs/global`), so
the index, every domain, and the generated per-domain baselines are a live view
of source: every current and later source child resolves through it, and no
domain can ever be partially deployed. The source `index.yaml` is already
written with deployment-relative (`~/.teleclaude`) paths, so it needs no
post-deploy rewrite. For each source `docs/global/<domain>/baseline.md` the
deploy inflates the domain baseline and writes it as a generated, gitignored
file beside its manifest at `docs/global/<domain>/domain-baseline.md`, visible
through the symlink at `~/.teleclaude/docs/<domain>/domain-baseline.md`. These
generated baselines are excluded from snippet iteration and validation, so they
are never treated as authored snippets. The SessionStart hook reads that file to
inject the domain's process-enforcement baseline. Global third-party docs are
read from the mother repo source (`docs/third-party/`), not from under the docs
symlink.

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
  And docs/global/ is exposed as a single whole-tree symlink at ~/.teleclaude/docs/
```

```
Scenario: UC-ARD2 Non-mother project sync skips global phase
  Given the project is not the Mother project
  And sync is invoked in deploy mode
  When the distribution pipeline runs
  Then the global phase produces no agent-home writes
  And the local phase deploys .agents/ to the project root
  And Codex commands still route to ~/.teleclaude/commands/
```

```
Scenario: UC-ARD3 Sync from a worktree uses worktree docs
  Given sync runs from a git worktree of the Mother project
  When the canonical-root resolver identifies the canonical root
  Then the docs source is the current worktree checkout
  And docs deployed reflect the worktree's branch through the single symlink, not main
```

```
Scenario: UC-ARD4 Sync establishes the single docs symlink as a live view
  Given a source domain docs/global/<domain>/ with a baseline.md and one or more subfolders
  When the documentation deployment step runs
  Then any stale real ~/.teleclaude/docs directory from an older deploy is removed
  And ~/.teleclaude/docs is a single symlink to the source docs/global
  And the inflated domain baseline is written to docs/global/<domain>/domain-baseline.md
  And that generated baseline is gitignored and excluded from snippet iteration and validation
  And a subfolder added to the source domain afterward resolves through the symlink without a re-deploy
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
- **config** — supplies the project root and the Mother project
  resolution used by the publishing gate.

## Known caveats

- Codex commands routing to `~/.teleclaude/commands/` (rather than
  `~/.codex/commands/`) is deliberate cross-project sharing. It
  surprises operators who expect symmetry with `~/.claude/` and
  `~/.gemini/`. The decision is intentional, not a bug.
- Documentation symlinks are read-only by convention. The single
  `~/.teleclaude/docs` symlink resolves onto the live source tree, so a stray
  edit through it mutates source; agents treat deployed docs as read-only.
- Worktree-aware docs sourcing prevents the easy bug of "synced from a
  worktree but deployed main-branch docs". A worktree whose `docs/` is
  missing, however, falls back silently rather than erroring.
- The distribution step is always fatal: a non-zero distribution exit propagates
  and fails the sync (there is no suppress-on-warn mode). The docs watcher, which
  must not block, catches that failure at its own subprocess boundary instead.
- The deployed `index.yaml` is the source `index.yaml` resolved through the
  symlink; it already carries `~/.teleclaude` paths and is not rewritten in
  place. Consumers see identical paths from the working tree and the deployed
  view — there is no deploy-time index divergence.
