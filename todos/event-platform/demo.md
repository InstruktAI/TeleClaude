# Demo: event-platform

## Medium

CLI + TUI. The event platform is a backend system — its observable surface is the
`telec events` CLI, the notification API, and the TUI notification panel.

## Validation

```bash
# 1. Verify the pipeline processes events end-to-end
telec events list
# Expect: all registered event types with domain, level, lifecycle status

# 2. Emit a test event and observe it flow through the system pipeline
# (requires daemon running with EventProcessor started)
telec sessions tail $(cat "$TMPDIR/teleclaude_session_id") --tools
# Expect: system pipeline cartridges logged in order: trust → dedup → enrichment → correlation → classification → projection

# 3. Verify notification projection works
curl -s --unix-socket /tmp/teleclaude-api.sock "http://localhost/api/events/notifications?limit=5"
# Expect: JSON array of notification objects with human_awareness and agent_handling fields

# 4. Verify domain pipeline fans out after system pipeline
# (requires at least one domain configured with cartridges)
telec config get event_domains
# Expect: domain configs with autonomy matrix, cartridge paths

# 5. Verify cartridge DAG resolution
telec config cartridges list --domain software-development
# Expect: cartridges listed in topological order with dependency info
```

## Guided Presentation

### Step 1: The event log is the source of truth

Show `telec events list` — all registered event types across system, signal, and domain
scopes. Point out the taxonomy structure: `system.*`, `signal.*`, `domain.{name}.*`.
This is the nervous system's vocabulary.

### Step 2: Events flow through the cartridge pipeline

Trigger a real event (e.g., daemon restart emits `system.daemon.restarted`). Tail the
session to observe the six system cartridges processing it in order. Each cartridge
annotates the envelope — trust flags, enrichment data, classification treatment. The
notification projector at the end decides whether this becomes a notification.

### Step 3: Domain pipelines run in parallel

Show a domain-scoped event entering the software-development domain pipeline after the
system pipeline completes. Domain cartridges execute their own DAG. Point out that
marketing and creative would run in parallel — independent domain stacks.

### Step 4: Autonomy controls what happens next

Show `telec config get event_domains.software-development.autonomy`. Demonstrate the
four-level hierarchy: event_type > cartridge > domain > global. Change one setting and
show how it affects pipeline behavior (e.g., set a cartridge to `manual` → it gets
skipped with a `cartridge.skipped` event).

### Step 5: The notification is a living object

Show a notification's two-dimensional state: human awareness (unseen/seen) × agent
handling (none/claimed/in_progress/resolved). Mark it seen via the API. Show how
lifecycle events (started → completed) update the same notification rather than
creating new ones.
