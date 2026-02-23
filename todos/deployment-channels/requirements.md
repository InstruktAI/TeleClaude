# Requirements: deployment-channels

## Goal

Implement the automated deployment pipeline: channel config, a webhook handler
that receives GitHub events via the hooks framework, and update execution logic.
Push to main or create a release → subscribing computers update automatically.
No polling, no signal files, no daemon loops.

## Scope

### In scope

1. **Channel config schema** — `deployment.channel` (alpha|beta|stable) and
   `deployment.pinned_minor` in teleclaude.yml, validated on daemon startup.
2. **Deployment webhook handler** — an internal hook handler registered in
   `HandlerRegistry` that receives normalized GitHub `HookEvent`s and decides
   whether to act based on the local channel config.
3. **Deployment contract** — a programmatic `Contract` registered at daemon startup
   matching GitHub push and release events, routing them to the handler.
4. **Update execution** — pull/checkout code, run migration runner, install,
   restart via exit code 42.
5. **Redis fan-out** — broadcast version-available event via internal event bus
   so all daemons evaluate against their own channel config (EventBusBridge
   handles the Redis transport).
6. **Update `telec version`** — show configured channel from config.
7. **Redis status reporting** — update deploy status keys during update lifecycle
   (same key pattern as current `deploy_service.py`).

### Out of scope

- Version detection via polling (replaced by webhooks)
- Signal file mechanism (not needed)
- Daemon background polling loop (not needed)
- `telec migrate` CLI (migrations are internal)
- Inbound webhook infrastructure (delivered by `inbound-hook-service`)
- Migration framework (delivered by `deployment-migrations`)

## Success Criteria

- [ ] `deployment.channel` configurable in teleclaude.yml with validation
- [ ] Default channel is `alpha` (backward compatible)
- [ ] Deployment contract registered at daemon startup
- [ ] Alpha: GitHub push to main triggers update
- [ ] Beta: new GitHub release triggers update
- [ ] Stable: new patch release within pinned minor triggers update
- [ ] Update sequence: pull/checkout → migrate → install → restart (exit 42)
- [ ] Migration failure halts update, reports status, does not restart
- [ ] Redis fan-out: all daemons receive version-available events
- [ ] Each daemon evaluates against its own channel config independently
- [ ] `telec version` shows configured channel
- [ ] Update lifecycle visible in Redis status keys

## Constraints

- Must use existing hooks framework (`HandlerRegistry`, `Contract`, `HookDispatcher`)
- Must reuse exit-code-42 restart mechanism (matches `deploy_service.py`)
- Must reuse Redis status key pattern (`system_status:{computer_name}:deploy`)
- Daemon remains running during migration; restart only after all steps complete
- Sessions survive daemon restart (confirmed in architecture docs)

## Dependencies

- `deployment-versioning` — for `__version__` and `telec version` base
- `inbound-hook-service` — for GitHub normalizer and inbound endpoint wiring
- `deployment-migrations` — for `migration_runner.run_migrations()`

## Risks

- **`git pull --ff-only` failure**: alpha assumes linear history. If ff-only
  fails, log error, skip update. Never force-pull.
- **Partial update state**: process dies between pull and install. Mitigation:
  migration runner tracks state, make install is idempotent, restart only after
  all steps succeed.
- **Webhook delivery failure**: GitHub retries for up to 3 days. If daemon is
  down, it gets the webhook on restart. For longer outages, next push triggers
  a fresh webhook.
- **Concurrent updates**: multiple daemons update simultaneously. Safe — each
  runs independently. No coordination needed.
