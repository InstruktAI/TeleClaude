---
id: 'project/spec/feature/context/agent-runtime-deployment'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Two-phase deployment of transpiled artifacts to per-agent home dirs, with Codex commands routed to a shared TeleClaude dir and docs atomically symlinked.'
---

# Agent Runtime Deployment — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

The phase of Sync that writes Deployed outputs each agent CLI reads at
runtime. When invoked via `telec sync`, `scripts/distribute.py` is always
called with `--deploy` (there is no no-deploy mode through the CLI). The
deploy path runs two phases:

1. **Global phase** — sources from `agents/` (Mother project only) are
   built under a temp dir `teleclaude-dist-global-*` and then deployed
   to per-agent user-home roots: `~/.claude/`, `~/.gemini/`, `~/.codex/`.
   The publishing gate ensures the global source list is only populated
   on the Mother project.
2. **Local phase** — sources from `.agents/` (any project) are built
   under `teleclaude-dist-local-*` and then deployed to the project
   root. Codex commands are an exception: they route to
   `~/.teleclaude/commands/` (NOT `~/.codex/commands/`) so commands are
   reusable across projects.

After both phases, the documentation tree is atomically symlinked from
source into `~/.teleclaude/docs/`, with `index.yaml` rewritten so
consumers see deployment-relative paths.

When `scripts/distribute.py` is invoked directly without `--deploy`,
agent artifacts are emitted to `project_root/dist/global` and
`project_root/dist/local` (not temp dirs), no copies are made to
`~/.<agent>/`, and `_deploy_documentation` is not called. This direct
no-deploy mode is for developers/CI inspecting build output, not for
`telec sync`.

## Canonical fields

### Use cases

```
Scenario: Mother project full sync with --deploy
  Given the project is the Mother project
  And sync is invoked with --deploy
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
  And sync is invoked with --deploy
  When the distribution pipeline runs
  Then the global phase produces no agent-home writes
  And the local phase deploys .agents/ to the project root
  And Codex commands still route to ~/.teleclaude/commands/
```

```
Scenario: Sync from a worktree uses worktree docs
  Given sync runs from a git worktree of the Mother project
  When _resolve_git_common_root identifies the canonical root
  Then the docs source is the current worktree checkout
  And docs deployed reflect the worktree's branch, not main
  And the deployed index.yaml is rewritten with the deployment root
```

```
Scenario: Sync repairs a broken docs symlink
  Given ~/.teleclaude/docs/ contains a broken or self-pointing symlink
  When _deploy_documentation runs
  Then the broken link is unlinked
  And a fresh atomic symlink is created to the docs source
  And third-party/ contents are preserved across the deploy
  And rewrite_global_index updates project_root and snippets_root in index.yaml
```

```
Scenario: scripts/distribute.py invoked directly without --deploy
  Given scripts/distribute.py is invoked directly (not through telec sync) without --deploy
  When the distribution pipeline runs
  Then agent artifacts are emitted under project_root/dist/global and project_root/dist/local
  And no temp dist dirs are used
  And no writes occur to ~/.claude/, ~/.gemini/, ~/.codex/
  And _deploy_documentation is NOT called
  And the dist/ output is left in place for inspection
```

### Implementation pointers (v1)

- `scripts/distribute.py:682-705` — `_resolve_git_common_root()` resolves the canonical root for worktrees.
- `scripts/distribute.py:753-758` — docs-source selection (worktree checkout vs canonical root).
- `scripts/distribute.py:778-785` — Codex command prefix and deploy target (`COMMANDS_DIR`).
- `scripts/distribute.py:839-870` — global vs local source collection branching on `is_mother_project`.
- `scripts/distribute.py:859-870` — `_existing_sources()` preserves `"agents"` and `".agents"` source entries even when their artifact subdirectories are absent.
- `scripts/distribute.py:1012-1016` — `AGENTS.override.md` write during the Codex local phase.
- `scripts/distribute.py:1100, 1178-1201` — two-phase deploy (global temp dir then local temp dir) under `if args.deploy:`.
- `scripts/distribute.py:1202-1224` — no-deploy branch writing under `project_root/dist/global` and `project_root/dist/local` (only reachable when distribute.py is invoked directly without `--deploy`).
- `scripts/distribute.py:1121-1123` — per-agent command artifact deployment.
- `scripts/distribute.py:1127-1176` — `_deploy_documentation()` atomic symlink logic with `third-party/` preservation.
- `scripts/distribute.py:658-679` — `rewrite_global_index()` updates `project_root` and `snippets_root` in the deployed `index.yaml`.
- `teleclaude/paths.py:30-31` — `GLOBAL_SNIPPETS_DIR` and `COMMANDS_DIR` constants.
- `teleclaude/sync.py:104-122` — `_run_distribute()` subprocess invocation; always appends `--deploy`, optionally `--warn-only`, and calls `subprocess.run(..., check=not warn_only)`.

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
- `--warn-only` is forwarded to the distribute subprocess. The
  subprocess return code is checked with `check=not warn_only`, so a
  warn-only run **suppresses** a non-zero distribute exit rather than
  surfacing it. Operators relying on the exit code to detect a
  distribute crash will see a silent success instead.
- The deployed `index.yaml` is rewritten in-place by
  `rewrite_global_index()`. Consumers reading the working-tree index
  will see different `project_root` values than the deployed one — this
  is expected, not drift.
