# Demo: event-platform

## Medium

CLI + API + TUI (WebSocket). The platform is a backend service — demonstration is through
observable behavior at the terminal and API level.

## Validation (automated)

```bash
# 1. Package boundary
python -c "from teleclaude_events import EventEnvelope, emit_event, EventCatalog; print('Package imports OK')"
grep -r "from teleclaude\." teleclaude_events/ && echo "FAIL: teleclaude imports found" || echo "PASS: no teleclaude imports"

# 2. Event catalog
telec events list

# 3. Separate database
ls -la ~/.teleclaude/events.db

# 4. API responds
curl -s http://localhost:8765/api/notifications?limit=5 | python -m json.tool

# 5. Daemon restart event exists
curl -s "http://localhost:8765/api/notifications?event_type=system.daemon.restarted&limit=1" | python -m json.tool

# 6. Old notification package removed
python -c "from teleclaude.notifications import NotificationRouter" 2>&1 | grep -q "ModuleNotFoundError" && echo "PASS: old package removed" || echo "FAIL: old package still exists"

# 7. Tests pass
make test && make lint
```

## Guided Walkthrough

### 1. The event envelope

Create an event in a Python REPL to show the five-layer structure:

```python
from teleclaude_events import EventEnvelope, EventLevel

e = EventEnvelope(
    event="domain.software-development.planning.todo_activated",
    version=1,
    source="demo",
    level=EventLevel.WORKFLOW,
    domain="software-development",
    visibility="local",
    description="Todo 'event-platform-core' activated for build",
    payload={"slug": "event-platform-core", "phase": "build"},
)
print(e.model_dump_json(indent=2))
```

Observe: identity, semantic (with visibility), data, affordances (None), resolution layers.

### 2. Emit through the pipeline

```python
from teleclaude_events import emit_event

stream_id = await emit_event(
    event="demo.presented",
    source="demo-session",
    level=EventLevel.OPERATIONAL,
    domain="system",
    visibility="local",
    description="Demonstration of the event platform",
    payload={"presenter": "claude"},
)
print(f"Event emitted: {stream_id}")
```

Check Redis: `redis-cli XLEN teleclaude:events` — stream length increased.

### 3. See the notification projection

The pipeline picks it up within ~1 second. Query the API:

```bash
curl -s http://localhost:8765/api/notifications?limit=1 | python -m json.tool
```

Observe: `human_status: unseen`, `agent_status: none`. This is the notification projection —
the Redis Stream is the event log, SQLite is the read model.

### 4. Notification state machine

```bash
# Mark seen
curl -s -X PATCH http://localhost:8765/api/notifications/1/seen | python -m json.tool

# Agent claims
curl -s -X POST http://localhost:8765/api/notifications/1/claim \
  -H 'Content-Type: application/json' \
  -d '{"agent_id": "demo-agent"}' | python -m json.tool
```

Two independent dimensions — human awareness and agent handling operate independently.

### 5. Pipeline in action

Show the cartridge pipeline processing an event:

- Event enters → deduplication cartridge checks idempotency key → passes through
- Notification projector reads lifecycle declaration → creates/updates SQLite row
- WebSocket push fires → TUI receives update
- Telegram adapter fires for high-level events

Emit a duplicate event with the same idempotency key — observe it's deduplicated (no new row).

### 6. Visibility levels

Show three events with different visibility:

```python
# Local — stays on this machine
await emit_event(event="system.health.check", visibility="local", ...)

# Cluster — reaches all computers
await emit_event(event="domain.software-development.build.completed", visibility="cluster", ...)

# Public — published to the mesh
await emit_event(event="cartridge.published", visibility="public", ...)
```

Observe: local events never leave the machine. Cluster events appear on other computers.
Public events would be forwarded to mesh peers (when mesh-distribution is implemented).

### 7. Dog-food: real platform events

```bash
# Show daemon restart event (emitted automatically on startup)
curl -s "http://localhost:8765/api/notifications?event_type=system.daemon.restarted" | python -m json.tool

# Trigger a todo DOR assessment, then show the resulting event
curl -s "http://localhost:8765/api/notifications?event_type=domain.software-development.preparation.dor_assessed" | python -m json.tool
```

### 8. Where dependents plug in

Explain the fan-out: `prepare-quality-runner` subscribes to `dor_assessed`. `todo-dump-command`
emits `todo.dumped`. `integrator-wiring` emits integration events. The event catalog and
producer API are ready for all of them.

### Progressive demo (later phases)

As each phase lands, the demo extends:

- **System cartridges**: show trust evaluation rejecting a malformed event, enrichment adding
  context, correlation detecting a failure cascade
- **Domain infrastructure**: show domain-scoped processing, personal subscription creation
- **Signal pipeline**: show feed ingestion → clustering → synthesis for a set of RSS feeds
- **Alpha container**: show an experimental cartridge running in the Docker sidecar
- **Mesh distribution**: show a public event arriving from a peer node
- **Domain pillars**: show out-of-box marketing or creative domain experience
