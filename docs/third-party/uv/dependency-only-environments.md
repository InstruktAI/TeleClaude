---
description: uv locked dependency-only synchronization for checking a source tree without an editable application fallback.
---

# Dependency-only environments

`uv sync --no-install-project` installs the project's dependencies while omitting
the project itself. Ordinary synchronization installs the project in editable
mode.

`--locked` rejects stale lock metadata instead of rewriting it. `--frozen` uses
the lock without checking that it matches project metadata. `--no-sync` skips
environment synchronization. These options have different guarantees: selecting
an environment for execution does not establish that it matches the checked
source's lock.

An exact sync removes extraneous packages.

## Sources

- https://docs.astral.sh/uv/concepts/projects/sync/ — editable installs, lock checks, exact synchronization and partial installation options.
