# Input: notification-service

<!-- Converged design from brainstorm session (breath cycle: inhale/hold/exhale). Session 3d2880de. -->

## Problem

TeleClaude has no unified notification system. Autonomous events (background workers, agent-to-agent decisions, job completions, external service callbacks) either fire into bespoke channel paths that nobody reads, or are silently lost. The admin has no single surface to see "what happened while I wasn't looking." Agents have no signal feed for autonomous events. Existing notification plumbing (notification_outbox, session outbox workers, hook outbox, job channel reports) is dead code that was never fleshed out into a real system.

## Core Concept

A **notification service** — an intelligent, schema-driven event processor that is the single source of truth for all autonomous platform events. Not a message broker. Not a dashboard. An event processor with domain knowledge expressed through schemas.

Every autonomous event flows through one pipe. The notifications table is the canonical event log for the entire platform. TUI, web frontend, Discord — they're all just readers of that pipe. Nothing delivers notifications on its own anymore. The pipe is the truth, the clients are projections.

### What a notification IS

A notification is a **living object** with a state machine that multiple actors (agents and humans) interact with across multiple surfaces, all staying in sync. It is not a fire-and-forget message.

Sometimes a notification is purely informational (read and done). Sometimes it points at a work item that has its own lifecycle — and the notification becomes a window into that lifecycle. The notification doesn't own the work. It gives you a view into whatever is happening inside it.

Analogy: GitHub PR notifications. You get a notification. The PR has its own lifecycle. The notification doesn't manage the PR — it keeps surfacing the PR's state back to you at meaningful transitions.

### What a notification is NOT

- Not a task manager (todos do that)
- Not a message broker (Redis does that)
- Not a rendering engine (clients do that)
- Not a replacement for transcripts or mirrors (those are forensics and recall)

## Architecture

### Separate package, daemon-hosted

The notification service is a **separate Python package** within the monorepo. Clean dependency direction: `teleclaude` imports from the notification package, never the reverse. The notification package has no imports from `teleclaude.*`.

The daemon hosts it — starts it on startup, stops it on shutdown. The daemon is a runtime host, not the owner. Like a web framework hosting middleware. The notification package could theoretically run in any Python host process.

**Separate SQLite database.** The notification service owns its own storage. This doesn't violate the single-database policy (that's about the daemon's data; this is a separate service's data). Benefits: no write contention with the main daemon DB, independent lifecycle (backup, reset, migration), clean ownership.

### Event-sourcing architecture (right-sized)

- **Redis Stream** = the event log. Append-only, ordered, persistent, replayable. Producers append events via `XADD`. The notification processor consumes via a consumer group.
- **SQLite** (separate file) = the read model / projection. Current state of all notifications, queryable by clients.
- **Notification processor** = the projection function. Reads events from the stream, applies schema rules, updates the SQLite read model, fans out to clients.

Why not Kafka/Pulsar/EventStoreDB? Scale mismatch. Hundreds of events per day across a few computers. Redis Streams + SQLite is perfectly right-sized. If this outgrows Redis Streams someday, swap the ingress for NATS JetStream or Kafka without changing the processor or the read model.

### Redis Streams solves the reliability problem

Redis pub/sub is fire-and-forget. Redis Streams are persistent. If the daemon restarts (which happens frequently in development), the notification processor reconnects to the consumer group and picks up exactly where it left off. Zero message loss. Producers never block — they append to the stream regardless of who's reading.

This eliminates the need for a separate daemon process. The persistence is in Redis, not in the process. The daemon can restart freely; the gap is just latency (seconds), not data loss.

## Schema-Driven Intelligence

### The schema IS the intelligence

A payload walks in with a certain shape. The processor doesn't have a switch statement for each type — it reads the schema metadata and derives the correct behavior. Adding a new notification type is **zero code in the processor** — you define a schema, register it, and the processor knows how to handle payloads of that shape.

### What schemas express

- **Identity**: how to deduplicate (idempotency key derivation from payload fields)
- **Update semantics**: which payload field changes constitute a meaningful transition (reset to unread) vs a silent update (progress tick — just update in place)
- **Terminal conditions**: when is this notification done (100% progress, entity in terminal state, explicit resolution)
- **Agent eligibility**: can agents claim and act on this notification type? (`actionable: true/false`)
- **Append behavior**: some fields accumulate (retries appended as array), others overwrite
- **Referenced entity type**: what `telec://` URI this notification points at (if any)

### Schema implementation (start simple)

Pydantic models in the notification package. If schema evolution becomes complex later, migrate to JSON Schema or Protocol Buffers for formal versioning and backward compatibility validation. But start with Python-native.

## Notification Categories

### Informational

No external reference. Read and done. Examples: "Mirror indexing complete — 3,660 sessions in 4m 12s", "Daemon restarted."

### Entity-referenced

Points at a resource via `telec://` URI. Reflects that resource's lifecycle. Examples: "DOR passed for history-search-upgrade" (references `telec://todo/history-search-upgrade`), "Deployment failed: instrukt-proxy" (references `telec://deployment/abc`). The notification surfaces state changes from the referenced entity without managing the entity itself.

### Progress

A long-running operation with evolving content. Same notification ID, content updates in place. Example: "Mirror indexing: 0/3660" evolves to "1200/3660" evolves to "3660/3660 complete." The processor knows from the schema that progress ticks are silent updates (no unread reset) until the terminal condition (100%) which IS a meaningful transition.

## Notification State Machine

Two orthogonal dimensions:

### Human awareness

`unseen` -> `seen`

### Agent handling (for actionable notifications)

`none` -> `claimed` -> `in_progress` -> `resolved`

These are independent. An agent can resolve something the human hasn't seen yet. A human can see something no agent has touched. The list view shows both at a glance.

### State transition rules

- **State transitions on an existing notification do NOT create new notifications.** Agent claims it? Update the record, push to all surfaces. No "Agent X read your notification" noise.
- **Only when resolution produces something genuinely new** (a bug was filed, a deployment was triggered) does a NEW notification get created for that new event.
- **Meaningful transitions** reset to unread (entity state changed, error occurred, resolution attached).
- **Progress ticks** update silently (content changes but nature hasn't changed).
- The schema determines which transitions are meaningful vs silent.

### Agent resolution

When an agent resolves a notification, it attaches a structured result:

```json
{
  "summary": "Restarted mirror worker, indexing resumed",
  "link": "telec://session/abc123",
  "resolved_by": "claude",
  "resolved_at": "2026-02-27T14:00:00Z"
}
```

Admin sees the resolution without leaving the notification list. Self-contained.

### Stale claim prevention

If a notification is in `claimed` or `in_progress` for more than N minutes without resolution, the claim expires. Returns to `none`. Another agent or human can pick it up. Simple deadlock prevention.

## Stateful Delivery

### All surfaces stay in sync

Notifications are tracked by ID in every client, just like session messages. When a notification state changes in one surface (read in TUI), ALL reflections update (Discord message edited, web frontend refreshed). No out-of-sync states.

- **TUI**: notifications enter the cache system the same way sessions do. WebSocket events for state changes. Same architecture, new entity type.
- **Web frontend**: admin notifications panel. Same API, rendered in browser.
- **Discord**: #notifications channel. Messages posted on creation, edited in place on state changes. Stateful, just like session messages.

### Delivery mechanism

All clients support push. On notification creation or state change:

1. Update SQLite read model
2. Push event via WebSocket to connected TUI/web clients
3. Post/edit Discord message via bot
4. Clients receive structured JSON payloads and render using client-side templates

### Client-side rendering

Notifications are **structured JSON payloads**, not markdown. Each notification type has a sub-schema that expresses its shape. Clients use templates to render the structured data appropriately for their medium. The notification service never produces presentation — it produces data. Templates live in the clients.

## telec:// URI Scheme

### Platform-wide resource addressing

Every entity in TeleClaude gets a canonical URI: `telec://{type}/{id}`

- `telec://todo/history-search-upgrade`
- `telec://session/abc123`
- `telec://deployment/v2.4.1-staging`
- `telec://bug/mirror-worker-crash`
- `telec://notification/42`

### Resolution

Each client implements a resolver that maps `telec://` URIs to navigation:

- **TUI**: resolves to view + params (switch to Sessions tab, highlight session abc123)
- **Web frontend**: resolves to URL path (`/admin/todos/history-search-upgrade`)
- **Discord**: displays as text or links to web frontend URL
- **Agents**: resolves to API endpoint for fetching the resource

### Registry

Start with hardcoded types: `todo`, `session`, `deployment`, `bug`, `notification`, `job`. Extract to a discoverable registry if/when more types emerge.

## External Service Integration

### Callback envelope pattern

When TeleClaude requests work from an external service (deployment platform, future services):

1. TeleClaude creates a partially-filled notification payload — the **envelope** — conforming to a known schema
2. The envelope is sent along with the service request (via Redis or API)
3. The external service does its work, enriches the payload with result fields
4. The enriched payload is sent back via `XADD` to the notification Redis Stream
5. The notification processor receives what is essentially its own schema coming home with new data
6. It processes it like any other notification — the schema dictates behavior

External services never need to understand TeleClaude's notification internals. They just fill in the blanks on the form they were given and return it. TeleClaude stays in control of the schema, the lifecycle, and the rendering.

### Internal service notifications

When an external service is consumed (requested, in-progress, delivered), the notification service creates internal notifications tracking the lifecycle. Admin sees: "Deployment requested" -> "Deployment in progress" -> "Deployment complete — v2.4.1 on staging."

## Idempotency

### Deduplication

Each notification has an idempotency key derived from payload fields (defined per schema). If the same event fires twice (session_closed replay, worker retry), the second write is either:

- Deduplicated (same key, same content = no-op)
- Appended (same key, new content = added to array). First invocation creates, second invocation appends. The notification body shows all invocations and their results.

The schema declares which fields participate in the idempotency key and whether duplicates are dropped or appended.

## Referential Integrity

When a referenced entity is deleted (todo removed, session purged), the notification transitions to a terminal state silently — "stale" or "archived." No ping to anyone. It just stops being active. If a consumer scrolls past it, they see it greyed out or gone. No action required from the consumer.

Integrity checks can run lazily (when a notification is accessed) or periodically (daemon maintenance task). Not eagerly on every entity deletion — that would couple the notification service to every entity lifecycle.

## Consolidation

### What gets replaced

ALL existing bespoke notification paths collapse into this service:

- `notification_outbox` table and related workers — replaced
- Session outbox workers for notification delivery — replaced
- Hook outbox notification paths — replaced
- Job reports going directly to channels — replaced (jobs create notifications instead)
- Any direct channel posting for operational events — replaced

This is greenfield. The existing notification plumbing is dead code. Remove it and build the notification service as the single path.

## What Generates Notifications

Only autonomous things the user didn't initiate:

- **Background workers**: mirror indexing progress/completion, future processors
- **Job reports**: cron jobs create notifications instead of posting to channels
- **Agent-to-agent outcomes**: when peer agents converge on a decision, the conclusion is a notification
- **System health**: daemon restart, migration applied, worker crashed
- **Todo state transitions**: DOR passed, build complete, review needs human decision
- **External service callbacks**: deployment complete, service response received
- **Errors that need attention**: actionable errors, not every error

### What does NOT generate notifications

- User-initiated actions (they already see the result)
- Normal agent turns (that's transcript/mirror territory)
- Internal daemon housekeeping that succeeds silently
- Reading/acknowledging a notification (no echo noise)

## Notification as Agent Signal Source

The notification inbox IS an observability pipeline for autonomous events. Gathering agents (periodic AI agent sessions that scan the platform for signals) can query the notification API: "show me all unread notifications from the last 24 hours." They get a structured list of everything that happened autonomously. No separate observability infrastructure needed.

This was a key insight from the brainstorm: we don't need a separate metrics/observability pipeline. The notification service IS the signal surface for agents. If an event matters enough to notify a human, it matters enough for an agent to ingest as a signal.

## Relationship to history-search-upgrade

The notification service is a **dependency** for history-search-upgrade. The mirror worker needs to report progress and completion through notifications. Without the notification service, the mirror worker would have to use bespoke channel posting — which is exactly the pattern we're eliminating.

Dependency chain: notification-service -> history-search-upgrade (mirrors use notifications for operational reporting).

## Relationship to harmonize-agent-notifications

The existing `harmonize-agent-notifications` todo is subsumed by this work. That todo was about harmonizing existing bespoke notification paths. This todo replaces them entirely with a proper service. The harmonize todo should be closed/absorbed.

## Technology Choices

| Concern                     | Solution                                     | Rationale                                                      |
| --------------------------- | -------------------------------------------- | -------------------------------------------------------------- |
| Event persistence / ingress | Redis Streams                                | Already running Redis, persistent, replayable, consumer groups |
| Current state / queries     | SQLite (separate file)                       | Lightweight, zero ops, owned by notification service           |
| Schema enforcement          | Pydantic models                              | Python-native, start simple, migrate to JSON Schema if needed  |
| Event processing            | Custom processor in notification package     | Hundreds of events/day, no framework needed                    |
| Client delivery             | WebSocket push (TUI/web) + Discord bot (API) | All clients already support push                               |
| Resource addressing         | `telec://` URI scheme                        | Platform-wide, client-resolved                                 |

## Design Process

This design was produced through a structured brainstorm session between Mo and Claude during a prepare-phase review of history-search-upgrade. The notification need surfaced from the mirror worker's requirement for operational reporting. The conversation expanded through three phases:

1. **Inhale**: explored notification needs across the platform — background workers, agent observability, external services, cross-project integration
2. **Hold**: crystallized key tensions — daemon-coupled vs standalone, markdown vs structured JSON, separate daemon vs Redis Streams for reliability, Kafka vs right-sized tools, notification-as-work-item vs notification-as-window-into-work
3. **Exhale**: converged on schema-driven intelligent processor, event-sourcing with Redis Streams + SQLite, callback envelope pattern for external services, `telec://` URI scheme, stateful delivery across all surfaces
