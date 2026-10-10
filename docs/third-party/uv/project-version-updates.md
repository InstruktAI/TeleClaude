---
description: uv project-version updates and the distinction between re-locking, environment synchronization, and frozen metadata changes.
---

# Project version updates

`uv version` reads or updates the project's version. An explicit value selects
the new version; `--bump` selects version arithmetic instead. The command's
`--no-sync` option skips virtual-environment synchronization after re-locking.
`--frozen` updates the project version without re-locking, so it is not evidence
that the lockfile carries the new project version.

The lockfile is managed by uv. Package upgrades are requested separately from a
version update. Successful version-command output does not report a comparison
of the dependency resolutions before and after the update.

## Sources

- https://docs.astral.sh/uv/reference/cli/#uv-version
- https://docs.astral.sh/uv/guides/projects/
