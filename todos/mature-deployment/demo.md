# Demo: mature-deployment

## Medium

CLI + GitHub web UI + daemon logs

## What the user observes

### 1. Version & channel awareness

```bash
telec version
# TeleClaude v1.3.0 (channel: beta, pinned: n/a)
```

The computer knows what version it runs, what channel it subscribes to, and
what it's eligible to receive.

### 2. Push-triggered alpha update

Developer pushes a commit to main. Within 5 minutes, the alpha-subscribed dev
machine detects the new commit, pulls, runs any migrations, installs, and
restarts the daemon. No human action required.

Verification:

```bash
# On alpha machine, check daemon logs after push
instrukt-ai-logs teleclaude --since 5m --grep "update"
# Shows: "Version watcher: new commit detected on main"
# Shows: "Auto-update: pulling main, running migrations, restarting"
```

### 3. Release-triggered beta update

A GitHub release is created (e.g. v1.3.0). Beta-subscribed machines detect the
new release, pull the tagged version, run migration manifests for the version gap,
install, and restart.

Verification:

```bash
# On beta machine
telec version
# TeleClaude v1.3.0 (channel: beta)
```

### 4. Migration self-healing

A minor release includes a config schema change. The migration manifest
automatically transforms the config. No manual steps. The machine before and
after shows the config is valid.

### 5. No more telec deploy

```bash
telec deploy
# Error: unknown command 'deploy'. Deployment is now automatic via channels.
# See: telec version
```

## Validation commands

```bash
telec version                    # Confirms version and channel
make status                      # Confirms daemon healthy after auto-update
cat ~/.teleclaude/migration_state.json  # Shows completed migrations
```
