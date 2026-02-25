# Requirements: mature-deployment

## Goal

Replace the manual `telec deploy` command with a fully automated deployment
pipeline where pushing to main (or creating a release) triggers deployment
to subscribing computers without human intervention. Every breaking change
ships with migration manifests that auto-reconcile, eliminating manual
upgrade steps.

## Scope

### In scope

1. **Channel subscription model** — computers declare alpha/beta/stable in config
2. **Version watcher job** — daemon background job that detects new versions
3. **Auto-deploy mechanism** — pull + migrate + install + restart on version change
4. **Migration manifest format** — numbered, ordered, idempotent migration scripts
5. **Migration runner** — diffs current vs target version, runs migrations in sequence
6. **CI pipeline** — GitHub Actions for test/lint/release creation on push to main
7. **Semantic versioning** — proper version management in pyproject.toml
8. **Remove telec deploy** — delete command, MCP tool, deploy_service.py, procedure doc

### Out of scope

- Frontend deployment (frontend has its own build/deploy concerns)
- Docker/container-based deployment
- Blue-green or canary deployment strategies
- Multi-repo deployment coordination
- Automated rollback (rollback is manual; migration failure halts and reports)

## Success Criteria

- [ ] Push to main triggers alpha subscribers to auto-update within 5 minutes
- [ ] Creating a GitHub release triggers beta subscribers to auto-update
- [ ] Stable subscribers only receive patch-level updates for their pinned minor
- [ ] Migration manifests run automatically during upgrade, in order
- [ ] A migration failure halts the upgrade and reports status (no silent partial state)
- [ ] `telec deploy` command and MCP tool are fully removed
- [ ] CI pipeline runs tests and lint on every push to main
- [ ] CI creates GitHub releases from tags
- [ ] Version is tracked in pyproject.toml and queryable at runtime

## Constraints

- Must use existing cron/jobs infrastructure for the version watcher
- Must work without Redis (alpha channel polls git remote directly)
- Redis transport can optionally broadcast version-available notifications for faster propagation, but polling is the fallback
- Migration scripts must be idempotent (safe to re-run)
- The daemon must continue running during migration; restart happens only after all migrations complete
- No new external dependencies (no webhook servers, no additional services)

## Risks

- **Migration script quality**: if a migration is not idempotent, re-runs cause corruption. Mitigation: migration runner validates idempotency markers.
- **Partial migration state**: if the process dies mid-migration. Mitigation: each migration records completion; runner resumes from last incomplete.
- **Git fetch overhead**: alpha channel polling git remote every 5 min. Mitigation: lightweight `git fetch --dry-run` or `git ls-remote` to check HEAD without pulling.
- **Service interruption**: restart during active sessions. Mitigation: existing graceful shutdown handles this (sessions survive daemon restart).

## Decomposition note

This todo is large. It should be decomposed into sequential sub-todos:

1. **Versioning foundation** — semantic versioning, version at runtime, CI pipeline
2. **Channel config + version watcher** — config schema, background job
3. **Migration framework** — manifest format, runner, completion tracking
4. **Auto-deploy integration** — wire watcher + migrations + restart
5. **Cleanup** — remove telec deploy command, MCP tool, deploy_service, procedure doc
