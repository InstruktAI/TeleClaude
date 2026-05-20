---
id: 'project/spec/feature/integration/deployment-version-fanout'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Cross-host Redis stream consumer that fans out deployment version_available events to every daemon in the cluster, with self-skip on origin to avoid double-execution.'
---

# Deployment Version Fanout — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

A long-running async task on each daemon (`_deployment_fanout_consumer`)
that reads from the Redis stream `DEPLOYMENT_FANOUT_CHANNEL` and dispatches
each message as a local HookEvent through the daemon's own HookDispatcher.
This fans out a deployment version-available signal to all daemons in the
cluster: when one daemon receives a GitHub release webhook (or otherwise
detects a new version), it publishes a `source="deployment"`,
`type="version_available"` event onto the Redis stream; every other daemon
reads it and runs its local update flow.

Self-origination is detected via a `daemon_id` property carried in the
event payload; a daemon skips messages with `daemon_id == config.computer.name`
to avoid re-executing an update it scheduled directly from the
github-source path. The originating daemon publishes the fanout
**before** scheduling its local `execute_update` task (publish is
awaited; `execute_update` is launched fire-and-forget via
`asyncio.create_task`), so remote daemons can begin their update in
parallel with the local one.

## Canonical fields

### Use cases

#### UC-DF1: Remote daemon receives the fanout and runs the update

```gherkin
Given daemon A on host "alpha" received a GitHub release webhook and entered handle_deployment_event with should_update=True
And A awaits _publish_fanout(version_info), which xadd's a HookEvent (source="deployment", type="version_available", properties.daemon_id="alpha") onto DEPLOYMENT_FANOUT_CHANNEL
And only AFTER the publish returns, A schedules its own local update as asyncio.create_task(execute_update(channel, version_info, get_redis), name=f"deploy-update-{channel}")
When daemon B on host "beta" reads the stream via xread
Then it decodes the event_json bytes
And reconstructs HookEvent.from_json(event_json)
And detects properties.daemon_id == "alpha" != config.computer.name ("beta")
And calls dispatcher.dispatch(event)
And the dispatcher matches the built-in deployment-fanout Contract
And handle_deployment_event runs on daemon B (with event.source="deployment", so no second fanout is published — only github-source events publish)
And handle_deployment_event on B schedules its own execute_update task

The originating daemon's publish-before-execute ordering means: when the
publish fails, remote daemons miss the fanout but A still proceeds with
its local update; when execute_update fails, the fanout has already
gone out to other daemons.
```

#### UC-DF2: Self-skip to avoid double execution

```gherkin
Given daemon A reads its own message from the stream
When the consumer evaluates event.properties.daemon_id == config.computer.name
Then it logs "Deployment fanout: skipping self-originated message" at debug
And does NOT dispatch — the github-source path is the same `handle_deployment_event` call that awaits `_publish_fanout` and then schedules the local `execute_update` task after the publish returns
```

#### UC-DF3: Stream cursor starts at "$" — only new messages

```gherkin
Given the daemon starts up
When _deployment_fanout_consumer initializes
Then last_id is set to "$" so xread reads only messages published AFTER startup
And no historical messages are replayed on daemon restart
```

#### UC-DF4: Decoding tolerance for bytes / str

```gherkin
Given xread may return data values as bytes (from the redis-py client) or strings
When the consumer reads data.get(b"event") or data.get("event")
Then it tries both encodings
And decodes bytes via .decode() before passing to HookEvent.from_json
```

#### UC-DF5: Dispatch failure is logged and consumption continues

```gherkin
Given event_json fails to parse or dispatcher.dispatch raises
When the consumer catches the exception
Then a warning "Deployment fanout: dispatch failed" is logged with the exception
And the consumer continues with the next message (does NOT halt)
And last_id is still advanced (the failed message is not retried)
```

#### UC-DF6: Redis error backoff

```gherkin
Given the consumer encounters a Redis connectivity error
When the outer try/except catches the exception
Then a warning "Deployment fanout consumer error" is logged
And the consumer sleeps for 5 seconds
And loops back to retry _get_redis() + xread
```

#### UC-DF7: Shutdown via cancellation

```gherkin
Given the daemon's shutdown_event is set OR the task is cancelled
When asyncio.CancelledError is raised in xread
Then the consumer's loop exits cleanly
And "Deployment fanout consumer stopped" is logged
```

### Implementation pointers (v1)

- `teleclaude/daemon_event_platform.py` —
  `_deployment_fanout_consumer` (L586, the consumer loop),
  task creation at L515 inside `_init_webhook_service`:
  `self._deployment_fanout_task = asyncio.create_task(
self._deployment_fanout_consumer(dispatcher, redis_transport),
name="deployment-fanout")`.
- Built-in contract registration inside `_init_webhook_service`
  (~L500): `Contract(id="deployment-fanout",
source_criterion=PropertyCriterion(match="deployment"),
type_criterion=PropertyCriterion(match="version_available"),
target=Target(handler="deployment_update"), source="programmatic")`.
- `teleclaude/deployment/handler.py` —
  `handle_deployment_event` (L72, runs for both github- and
  deployment-source events),
  `configure_deployment_handler` (L34),
  `_publish_fanout` (L161, awaited BEFORE the local execute_update
  task is scheduled),
  `_log_execute_update_task_exception` (L67).
  `execute_update` lives in `teleclaude/deployment/executor.py`.
- `DEPLOYMENT_FANOUT_CHANNEL = "deployment:version_available"` constant
  in `teleclaude/deployment/handler.py`.
- `teleclaude/transport/redis_transport.py` — `RedisTransport._get_redis`
  for client access.

### Cross-context references

- Cluster-scoped delivery — every daemon in the deployment runs its own
  consumer. The mechanism is the v1 expression of the v2 domain spec's
  `EventVisibility.CLUSTER` posture for cross-context events.
- Initial trigger sources include `github-webhook-normalization`
  (push / release events) and any other path that emits
  `source="deployment"` / `type="version_available"` through the
  daemon's local dispatcher.
- Consumer dispatches through `eventbus-hook-bridge`'s dispatcher
  (sharing the Contract matcher and handler registry).
- The `deployment_update` handler lives outside `integration`
  (in `teleclaude/deployment/`); this snippet documents the
  integration-side transport, not the deployment business logic.

## Known caveats

- Uses Redis **streams** (xread) with a per-consumer `last_id` cursor.
  Crash recovery starts from `"$"` — meaning unread messages published
  while the daemon was down are NOT replayed. This is a deliberate
  simplification: the github-source daemon retries publish on its own
  cadence, and the deployment system has eventual-consistency
  guarantees that tolerate skipped fanouts.
- `xread` blocks for up to 5000 ms per call to keep the loop responsive
  to shutdown signals (count=10, block=5000).
- Self-skip relies on `config.computer.name` matching the
  `daemon_id` written by the publishing daemon — naming drift between
  the publisher and the local computer config would defeat the
  self-skip and could re-execute updates.
- The consumer does NOT dedupe across messages; if the same version
  message is published twice with different `daemon_id` values, both
  remote daemons would dispatch (and the deployment handler must be
  idempotent to absorb).
- This is the only Redis-stream-based dispatch path in v1 integration;
  all other event flows are local HookOutbox or in-process EventBus.
- Per-message backpressure is bounded only by `count=10` per `xread`
  call; under high publish rates the consumer can fall behind without
  observable signal beyond delayed dispatch.
