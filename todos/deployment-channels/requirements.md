# Requirements: deployment-channels

## Goal

Introduce a deployment channel subscription model so each computer declares which
version stream it follows (alpha/beta/stable), and a background job detects when
new versions are available.

## Scope

### In scope

1. **Channel config schema** — `deployment.channel` (alpha|beta|stable) and
   `deployment.pinned_minor` in config.yaml, validated on daemon startup.
2. **Version watcher job** — a script job in the cron runner that checks for
   newer versions based on channel and writes a signal file when one is found.
3. **Signal file** — `~/.teleclaude/update_available.json` with current version,
   available version, and channel.
4. **Update `telec version`** — show actual channel from config instead of
   hardcoded "alpha".

### Out of scope

- Acting on the signal file (handled by `deployment-auto-update`)
- Migration framework (handled by `deployment-migrations`)
- Redis broadcast of version availability (deferred — polling is sufficient)

## Success Criteria

- [ ] `deployment.channel` is configurable in config.yaml with validation
- [ ] Default channel is `alpha` (backward compatible)
- [ ] Version watcher runs on cron schedule (every 5 minutes)
- [ ] Alpha: detects new commits on `origin/main` via `git ls-remote`
- [ ] Beta: detects new GitHub releases via GitHub API
- [ ] Stable: detects new patches within pinned minor via GitHub API
- [ ] Signal file written when newer version available, absent when current
- [ ] `telec version` shows configured channel

## Constraints

- Must use existing `jobs/` and cron runner infrastructure (schedule via teleclaude.yml)
- Must work without Redis (polling only)
- GitHub API calls must use authenticated requests to avoid rate limits
- `git ls-remote` must be lightweight (no fetch, no clone)

## Risks

- **GitHub API rate limits**: authenticated requests get 5000/hour, polling every
  5 min = 288/day — well within limits. Mitigation: use conditional requests
  (If-None-Match) to minimize payload.
- **Network failures**: version watcher must handle transient failures gracefully
  (log warning, retry next cycle, don't write stale signal).
