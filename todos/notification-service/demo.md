# Demo: notification-service

## Validation

```bash
# 1. Verify package exists and has no teleclaude imports
python -c "from teleclaude_notifications import EventEnvelope, NotificationProducer, EventCatalog; print('Package imports OK')"
grep -r "from teleclaude\." teleclaude_notifications/ && echo "FAIL: teleclaude imports found" || echo "PASS: no teleclaude imports"

# 2. Verify event catalog lists registered schemas
telec events list

# 3. Verify notification database is separate from daemon DB
ls -la ~/.teleclaude/notifications.db

# 4. Verify API endpoint responds
curl -s http://localhost:8765/api/notifications?limit=5 | python -m json.tool

# 5. Verify daemon restart event was emitted (should exist after daemon start)
curl -s "http://localhost:8765/api/notifications?event_type=system.daemon_restarted&limit=1" | python -m json.tool

# 6. Run tests
make test
```

## Guided Presentation

### Step 1: The package boundary

Show that `teleclaude_notifications/` is a self-contained package with no reverse imports.
Run `grep -r "from teleclaude\." teleclaude_notifications/` — expect no matches.
This proves the clean dependency direction: teleclaude imports from the notification package,
never the reverse. The package could run in any Python host process.

### Step 2: The event envelope

Show the envelope schema by creating one in a Python REPL:

```python
from teleclaude_notifications import EventEnvelope, EventLevel
e = EventEnvelope(
    event="demo.presented",
    version=1,
    source="demo-session",
    level=EventLevel.OPERATIONAL,
    domain="demo",
    description="Demonstration of the notification service",
    payload={"presenter": "claude", "audience": "admin"},
)
print(e.model_dump_json(indent=2))
```

Observe the five-layer structure: identity, semantic, data, affordances (None), resolution.

### Step 3: Emit an event

Use the producer to fire a test event through Redis Streams:

```python
from teleclaude_notifications import NotificationProducer
producer = NotificationProducer(redis_url="redis://localhost:6379")
await producer.emit(e)
```

Then check Redis: `redis-cli XLEN teleclaude:notifications` — the stream length increased.

### Step 4: See it in the read model

The processor picks it up within ~1 second. Query the API:

```bash
curl -s http://localhost:8765/api/notifications?limit=1 | python -m json.tool
```

Observe: the notification has `human_status: unseen`, `agent_status: none`.
This is the projection — Redis Stream is the event log, SQLite is the read model.

### Step 5: Notification state machine

Mark the notification as seen:

```bash
curl -s -X PATCH http://localhost:8765/api/notifications/1/seen | python -m json.tool
```

Observe: `human_status` changed to `seen`. The two dimensions (human awareness, agent handling)
are independent — an agent could resolve something the human hasn't seen yet.

### Step 6: The event catalog

Run `telec events list` to see all registered event types. Each type has a level, domain,
and description. Adding a new event type means defining a Pydantic schema and registering it.
Zero processor code changes.

### Step 7: Dog-food in action

Show a real notification from the daemon restart:

```bash
curl -s "http://localhost:8765/api/notifications?event_type=system.daemon_restarted" | python -m json.tool
```

This was emitted automatically when the daemon started. No manual trigger. The notification
service is already consuming its own platform events.

### Step 8: Where the dependents plug in

Explain: `prepare-quality-runner` will subscribe to `todo.artifact_changed` and `todo.dor_assessed`.
`todo-dump-command` will emit `todo.dumped`. The event catalog and producer API are ready for them.
Each dependent todo adds its own producers and consumers — the notification service is the shared
nervous system they all plug into.
