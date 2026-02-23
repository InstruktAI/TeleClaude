# Input: deployment-auto-update

## Context

Parent todo: `mature-deployment` (decomposed). Phase 4 of 5.
Depends on: `deployment-migrations`.

## Brain dump

Wires version watcher + migration runner + restart into a single automated flow.
When the version watcher detects a new version, the update executor handles the
full sequence: fetch → checkout/pull → migrate → install → restart.

### Update executor

- Watches for signal file from version watcher (`~/.teleclaude/update_available.json`)
- Alpha: `git pull --ff-only origin main`
- Beta/Stable: `git fetch --tags && git checkout v{version}`
- Runs migration runner for version gap
- Runs `make install`
- Triggers daemon restart via exit code 42 (existing mechanism)
- Updates deploy status in Redis (same key pattern as current)

### Daemon integration

- Register as background worker or cron job signal consumer
- Schedule update during low-activity window, or run immediately if idle
- Log update lifecycle events

### Open questions

- Should update happen during active sessions? Current graceful shutdown handles
  session survival, so probably yes.
- `git pull --ff-only` vs `git fetch + reset` for alpha? ff-only is safer but
  fails on force-push.
