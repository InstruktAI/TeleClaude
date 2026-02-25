# Input: deployment-channels

## Context

Parent todo: `mature-deployment` (decomposed). Phase 2 of 4.
Depends on: `deployment-versioning`, `deployment-migrations`, `inbound-hook-service`.

## Architecture revision (2026-02-23)

The original design used a cron-based version watcher that polled `git ls-remote`
and GitHub API every 5 minutes, writing signal files for a daemon background loop.
This was wrong. The inbound webhook infrastructure already exists. GitHub sends
webhooks. Use them.

**What this todo now covers:**

- Channel config schema (alpha/beta/stable) — unchanged concept
- Deployment webhook handler (receives GitHub HookEvents via hooks dispatcher)
- Update execution logic (pull/checkout + migrate + install + restart)
- Redis fan-out (broadcast to all daemons via EventBusBridge)
- `telec version` shows configured channel

**What was killed:**

- Version watcher cron job
- Signal file mechanism
- `deployment-auto-update` sub-todo (merged here)

## Key integration points

- `HandlerRegistry.register("deployment_update", handler)` — register internal handler
- `Contract(source_criterion, type_criterion, target=Target(handler=...))` — match events
- `EventBusBridge` — handles Redis fan-out automatically
- `os._exit(42)` — existing restart mechanism (launchd KeepAlive restarts daemon)
- `migration_runner.run_migrations()` — called during update sequence
