# Requirements: deployment-versioning

## Goal

Expose the project version at runtime and provide a CLI entry point for version
queries. This is the foundation that version comparison (channels, migrations,
auto-update) depends on.

## Scope

### In scope

1. **Runtime version access** — expose `__version__` from package metadata so
   any module can `from teleclaude import __version__`.
2. **`telec version` command** — prints current version, channel (default: alpha),
   and commit hash. Must work whether installed via `make install` or running from
   source.
3. **pyproject.toml version bump** — update from `0.1.0` to `1.0.0` as the
   starting point for the versioning initiative.

### Out of scope

- CI pipeline (already exists: `.github/workflows/lint-test.yaml`)
- Release workflow (already exists: `.github/workflows/release.yaml` with AI
  consensus-based release analysis, auto version bump, and GitHub Release creation)
- Deployment channel config schema (handled by `deployment-channels`)
- Version watcher or auto-update logic

## Success Criteria

- [ ] `from teleclaude import __version__` returns `"1.0.0"` (or current version)
- [ ] `telec version` prints version, channel, and short commit hash
- [ ] pyproject.toml version is `1.0.0`
- [ ] Existing CI pipeline (`make lint`, `make test`) passes with changes

## Constraints

- Use `importlib.metadata.version()` for runtime access (standard library, no
  new dependencies).
- `telec version` must not import the daemon or heavy modules.
- Channel display defaults to "alpha" until `deployment-channels` is implemented.

## Risks

- **Metadata unavailable in dev mode**: `importlib.metadata.version()` requires
  the package to be installed. When running from source without install, fall back
  to reading pyproject.toml directly. Mitigation: try/except with fallback.
