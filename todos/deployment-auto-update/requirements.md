# Requirements: deployment-auto-update

## Goal

Wire the version watcher signal, migration runner, and daemon restart into a
single automated update flow. When a new version is detected, the system pulls
code, runs migrations, installs, and restarts — without human intervention.

## Scope

### In scope

1. **Update executor** — reads the signal file from version watcher, executes
   the full update sequence: fetch, checkout/pull, migrate, install, restart.
2. **Daemon integration** — register the update executor as a background check
   that acts on the signal file.
3. **Update lifecycle logging** — log each step of the update for debugging.
4. **Status reporting** — update Redis status keys (same pattern as current
   deploy service) so other tools can query update state.

### Out of scope

- Version detection (handled by `deployment-channels` version watcher)
- Migration framework (handled by `deployment-migrations`)
- Rollback automation (failure halts and reports; rollback is manual)
- Low-activity window scheduling (first version runs immediately on signal)

## Success Criteria

- [ ] Signal file triggers update sequence automatically
- [ ] Alpha: `git pull --ff-only origin main`
- [ ] Beta/Stable: `git fetch --tags && git checkout v{version}`
- [ ] Migration runner executes for version gap
- [ ] `make install` runs after code update
- [ ] Daemon restarts via exit code 42 (existing mechanism)
- [ ] Update status visible in Redis
- [ ] Migration failure halts update, reports status, does not restart
- [ ] Signal file consumed (removed) after successful update

## Constraints

- Must reuse existing exit-code-42 restart mechanism
- Must reuse existing Redis status key pattern
- Daemon must remain running during migration; restart only after all steps complete
- Sessions survive daemon restart (confirmed in architecture)

## Risks

- **`git pull --ff-only` failure on force-push**: alpha channel assumes linear
  history. Mitigation: if ff-only fails, log error and skip cycle (don't force).
- **Partial update state**: if process dies between git pull and make install.
  Mitigation: migration runner tracks state, make install is idempotent, restart
  only happens after all steps succeed.
- **Concurrent sessions during restart**: existing graceful shutdown handles this.
  Sessions survive daemon restart per architecture docs.
