# Bin

## Required reads

- @docs/project/policy/bin-bootstrap-boundary.md
- @docs/project/policy/scripts-standalone-execution.md

## Purpose

`bin/` exists to bootstrap and initialize the platform, and to host lifecycle wrappers.

## Boundary

- Keep `bin/` limited to install/init/service-control/wrapper responsibilities.
- Do not add routine runtime tooling here.
- Do not add one-shot scripts, migration helpers, or AI scratch utilities here.

## Location Map

- `bin/`: bootstrap and lifecycle wiring (`install`, `init`, daemon/service wrappers).
- `scripts/`: stable public runtime command surface (symlinked to `~/.teleclaude/scripts`).
- `tools/`: internal engineering/platform tooling (lint, format, checks, test wrappers, migrations, worktree prep).
- `teleclaude/entrypoints/`: module entrypoints invoked with `uv run -m ...`.

## Placement Rule

If a file is not required to install, initialize, or lifecycle-manage TeleClaude, it does not belong in `bin/`.

