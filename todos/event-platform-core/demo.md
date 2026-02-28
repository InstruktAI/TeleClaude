# Demo: event-platform-core

## Validation

```bash
# 1. Package boundary
python -c "from teleclaude_events import EventEnvelope, emit_event, EventCatalog; print('Package imports OK')"
grep -r "from teleclaude\." teleclaude_events/ && echo "FAIL: teleclaude imports found" || echo "PASS: no teleclaude imports"

# 2. Event catalog
telec events list

# 3. Separate database
ls -la ~/.teleclaude/events.db

# 4. API responds (daemon API uses Unix socket, not HTTP port)
curl -s --unix-socket /tmp/teleclaude-api.sock "http://localhost/api/notifications?limit=5" | python -m json.tool

# 5. Daemon restart event exists (INFRASTRUCTURE level=0, domain=system)
curl -s --unix-socket /tmp/teleclaude-api.sock "http://localhost/api/notifications?domain=system&limit=1" | python -m json.tool

# 6. Old notification package removed
python -c "from teleclaude.notifications import NotificationRouter" 2>&1 | grep -q "ModuleNotFoundError" && echo "PASS: old package removed" || echo "FAIL: old package still exists"

# 7. Tests pass
make test && make lint
```

## Guided Presentation

### Step 1: The package boundary

Show that `teleclaude_events/` is a self-contained package with no reverse imports.
Run `grep -r "from teleclaude\." teleclaude_events/` — expect no matches.
The package could run in any Python host process.

### Step 2: The event envelope

Show the five-layer structure with visibility:

```python
from teleclaude_events import EventEnvelope, EventLevel, EventVisibility

e = EventEnvelope(
    event="domain.software-development.planning.todo_activated",
    version=1,
    source="demo",
    level=EventLevel.WORKFLOW,
    domain="software-development",
    visibility=EventVisibility.LOCAL,
    description="Todo 'event-platform-core' activated for build",
    payload={"slug": "event-platform-core", "phase": "build"},
)
print(e.model_dump_json(indent=2))
```

Observe: identity, semantic (with visibility field), data, affordances (None), resolution.

### Step 3: Emit through the pipeline

```python
from teleclaude_events import emit_event, EventLevel

stream_id = await emit_event(
    event="demo.presented",
    source="demo-session",
    level=EventLevel.OPERATIONAL,
    domain="system",
    description="Demonstration of the event platform",
    payload={"presenter": "claude"},
)
print(f"Event emitted: {stream_id}")
```

Check Redis: `redis-cli XLEN teleclaude:events` — stream length increased.

### Step 4: See the notification projection

The pipeline processor picks it up within ~1 second. Query the API:

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock "http://localhost/api/notifications?limit=1" | python -m json.tool
```

Observe: `human_status: unseen`, `agent_status: none`, `visibility: local`.
Redis Stream is the event log. SQLite is the notification projection.

### Step 5: Notification state machine

```bash
# Mark seen
curl -s --unix-socket /tmp/teleclaude-api.sock -X PATCH "http://localhost/api/notifications/1/seen" | python -m json.tool

# Agent claims
curl -s --unix-socket /tmp/teleclaude-api.sock -X POST "http://localhost/api/notifications/1/claim" \
  -H 'Content-Type: application/json' -d '{"agent_id": "demo-agent"}' | python -m json.tool
```

Two independent dimensions — human awareness and agent handling operate independently.

### Step 6: Deduplication

Emit the same event twice with the same idempotency key:

```python
await emit_event(event="system.daemon.restarted", source="daemon",
    level=EventLevel.INFRASTRUCTURE, domain="system",
    payload={"computer": "local", "pid": 12345})
# Emit again with same payload (same idempotency key derivation)
await emit_event(event="system.daemon.restarted", source="daemon",
    level=EventLevel.INFRASTRUCTURE, domain="system",
    payload={"computer": "local", "pid": 12345})
```

Query API — only one notification exists. The dedup cartridge dropped the duplicate.

### Step 7: Event catalog

Run `telec events list`. All registered event types with level, domain, visibility, and
description. Adding a new event type requires only a schema definition — zero pipeline changes.

### Step 8: Dog-food in action

```bash
# Daemon restart event (emitted automatically on startup; filter by domain=system)
curl -s --unix-socket /tmp/teleclaude-api.sock "http://localhost/api/notifications?domain=system" | python -m json.tool
```

This was emitted automatically. The platform is already consuming its own events.

### Step 9: Where dependents plug in

`prepare-quality-runner` subscribes to `dor_assessed`. `todo-dump-command` emits `todo.dumped`.
Each dependent todo adds producers and consumers — the event platform is the shared nervous
system they all plug into. Later phases add trust, enrichment, domain pipelines, and signal
processing without changing the core runtime.
