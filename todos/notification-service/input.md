# Input: notification-service

<!-- Converged design from brainstorm session (breath cycle: inhale/hold/exhale). Session 3d2880de. -->
<!-- Enriched with event-driven paradigm, affordance-based envelopes, consumption spectrum, and progressive automation insights. Session c40b16b6 (Feb 28 2026). -->

## Problem

TeleClaude has no unified notification system. Autonomous events (background workers, agent-to-agent decisions, job completions, external service callbacks) either fire into bespoke channel paths that nobody reads, or are silently lost. The admin has no single surface to see "what happened while I wasn't looking." Agents have no signal feed for autonomous events. Existing notification plumbing (notification_outbox, session outbox workers, hook outbox, job channel reports) is dead code that was never fleshed out into a real system.

Beyond notifications: scheduled jobs and ad-hoc dispatching create tight coupling and fragile chains. `telec bugs report` runs an entire lifecycle inline. Maintenance routines are scheduled instead of reactive. The platform has no event-driven execution model — things happen because something polls or a timer fires, not because a signal arrived.

## Core Concept

A **notification service** — an intelligent, schema-driven event processor that is the single source of truth for all autonomous platform events. Not a message broker. Not a dashboard. An event processor with domain knowledge expressed through schemas.

Every autonomous event flows through one pipe. The notifications table is the canonical event log for the entire platform. TUI, web frontend, Discord — they're all just readers of that pipe. Nothing delivers notifications on its own anymore. The pipe is the truth, the clients are projections.

This is not just a notification system. It is the **nervous system** of the platform — sensory input (events), processing (schema-driven routing), motor output (agent responses), awareness (multi-surface projections of the same truth).

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

## Event-Driven Job Execution

### Signal in, action out

The notification service replaces scheduled jobs with reactive event processing. Instead of cron-based polling ("every 5 minutes, scan for changes"), events fire when things happen and handlers react.

| Old pattern                      | New pattern                                             |
| -------------------------------- | ------------------------------------------------------- |
| Scheduled DOR scanner            | `todo.artifact_changed` → prepare-quality-runner reacts |
| `telec bugs report` inline chain | `bug.reported` → notification → agent claims and fixes  |
| Ad-hoc `next_prepare` passes     | `todo.created` / `todo.dumped` → automated preparation  |
| Manual content pipeline          | `content.dumped` → writer agent picks up                |

### The "dump" primitive

Two modes of creation, distinguished by whether a signal fires:

| Command                      | Signal                              | Processing                             |
| ---------------------------- | ----------------------------------- | -------------------------------------- |
| `telec todo create`          | No signal. Workspace for iteration. | Human-driven.                          |
| `telec todo dump`            | Fires notification immediately.     | Agent-driven via notification service. |
| `telec content dump`         | Fires notification immediately.     | Writer/publisher agents react.         |
| `telec bugs report` (legacy) | Inline dispatch (coupled).          | To be migrated to notification-driven. |

The dump is a fire-and-forget brain dump. The notification service routes it to subscribed handlers. The human's five-minute dump becomes a fully processed artifact without them touching it again.

### First internal consumers (dog-fooding)

- **prepare-quality-runner**: consumes `todo.artifact_changed`, `todo.created`, `todo.dumped`, `todo.activated`, `todo.dependency_resolved`. Produces DOR assessments as notification resolutions.
- **content pipeline**: consumes `content.dumped`. Writer agent refines, publisher agent distributes.
- **history-search-upgrade**: mirror worker reports progress/completion through notifications.

These prove the pattern before any external integration. TeleClaude is both the first producer and consumer of its own event stream.

## Event Levels

Same pipe, different significance. Consumers filter by level.

| Level | Name           | What                                                  | Who cares                      |
| ----- | -------------- | ----------------------------------------------------- | ------------------------------ |
| L0    | Infrastructure | Redis connected, worker spawned, GC ran               | Nobody unless something breaks |
| L1    | Operational    | Session started, mirror indexed, daemon restarted     | Operators, gathering agents    |
| L2    | Workflow       | DOR passed, build complete, review needs decision     | Orchestrators, the human       |
| L3    | Business       | Deployment delivered, customer escalation, SLA breach | The human, always              |

The level is a field in the envelope. An infrastructure agent subscribes to L0-L1. A human's TUI shows L2-L3 by default. An admin who wants everything? Turn the dial. Progressive disclosure through subscription, not through separate infrastructure.

## The Envelope Schema

### Telec as the shared codec

The wire format is JSON. The interpreter is telec. Everyone runs telec. That's the entire answer.

Producers use whatever internal models they want (Pydantic, dataclass, raw dict). They serialize to the envelope format and throw it at the pipe. Out the other end comes JSON. Telec parses it. Telec knows the shape because telec defines the shape. Schema versioning IS telec versioning. V1 telec reads V1 envelopes. V2 telec reads V1 and V2.

There is no coupling problem between producer and consumer packages. The producer's internal representation is their private business. The consumer never imports the producer's models. They both speak JSON through a shared codec.

### Envelope structure

```yaml
# === Identity: who am I ===
event: deployment.failed
version: 1
source: deployment-service
timestamp: 2026-02-28T10:00:00Z
idempotency_key: 'deploy:instrukt-proxy:v2.4.1:attempt-3'

# === Semantic: how to make sense of me ===
level: 3 # L0-L3 significance
domain: infrastructure # loose hint, not strict taxonomy
entity: 'telec://deployment/abc' # what I'm about
description: >
  Deployment of instrukt-proxy v2.4.1 to staging failed
  on attempt 3 of 3. Container health check timed out.

# === Data: what happened ===
payload:
  service: instrukt-proxy
  version: v2.4.1
  target: staging
  attempt: 3
  error: health_check_timeout
  logs_tail: '...'

# === Affordances: what can you do with me ===
actions:
  retry:
    description: Retry the deployment with same config
    produces: deployment.started
    outcome_shape:
      success: deployment.completed
      failure: deployment.failed
  escalate:
    description: Escalate to human operator
    produces: notification.escalation
  rollback:
    description: Roll back to previous stable version
    produces: deployment.started
    outcome_shape:
      success: deployment.completed

# === Resolution: what "done" looks like ===
terminal_when: 'action taken OR 3 hours elapsed'
resolution_shape:
  action_taken: string
  result: 'telec://deployment/{new_id}'
  resolved_by: string
```

The envelope has five layers:

1. **Identity** — who am I, where did I come from, how to deduplicate me
2. **Semantic** — how to make sense of me (level, domain, description, entity reference)
3. **Data** — what happened (the payload, varies by event type)
4. **Affordances** — what can you do with me (actions, outcomes, error shapes)
5. **Resolution** — what "done" looks like

The identity, semantic, and resolution layers are fixed — telec owns them. The data layer varies per event type. The affordance layer is the innovation — it's what makes events self-describing for consumers who have never seen them before.

### Self-describing events with affordances

Traditional event systems say: "here's a blob, you figure it out." The affordance layer says: "here's what you CAN do with me."

An AI agent that has never seen `deployment.failed` before reads the affordances and understands: I have three options (retry, escalate, rollback). Each one produces a specific event type. Each outcome has a known shape. I can reason about which action to take based on context I already have.

The agent doesn't need an SDK for the deployment service. It doesn't need to import anything. The event taught it what to do.

## The Consumption Spectrum

Every consumer chooses where they sit on this spectrum:

```
TIGHT ←————————————————————————→ LOOSE

Dog food         Automation        AI-assisted        Discovery
(us consuming    (they built a     (AI interprets     (AI explores
our own events,  parser for our    unfamiliar events,  what's even
full knowledge)  versioned shape)  routes by heuristic) available)
```

### Tight (dog-fooding)

We produce and consume our own events. Full knowledge. Predictable wiring. Our handlers know the exact payload shape because we wrote the producer. This is our dog food — tight because we choose it, not because the system demands it.

### Automation

An external consumer inspects the envelope version, maps the payload fields, builds a deterministic parser. No AI needed. Wire-to-wire. They chose to codify the consumption because they want it all the time.

### AI-assisted

A consumer who has never seen our events before points their AI at the stream. The AI reads the description, reads the affordances, and makes a judgment call about relevance and action. Loose. No schema import. No shared library. Intelligence in the middle.

This is where AI-native event processing is genuinely different from traditional systems. A traditional code handler CANNOT reason about an unfamiliar event. An AI handler CAN — if the metadata is rich enough. The affordance layer makes the metadata rich enough.

### Discovery

A new consumer explores what's available:

```
telec events discover "infrastructure failures"
telec events discover "anything about deployments"
telec events watch --interest "business-level events I should act on"
```

Not a filter on event type. A filter on meaning. The AI reads each incoming event's description and affordances, checks if it matches the interest, and routes it.

## Progressive Automation

### Discover → interpret → approve → codify → consume

When a new service publishes its event catalog:

1. **Discover**: AI sees new event types. Notifies the admin: "deployment-service published 3 new event types."
2. **Interpret**: AI reads the descriptions and affordances. Reports: "These look like infrastructure lifecycle events. We might want to react to failures."
3. **Approve**: Admin gets a notification with an action: "Want me to wire up automatic handling for deployment failures?" Button press. Or, for areas with higher AI clearance, this happens autonomously.
4. **Codify**: An AI coder takes the loose event description and generates tight plumbing — a handler, a parser, a route into internal systems. Out of the box building blocks. The codification follows a known approach and schema that telec provides.
5. **Consume**: The next time the event fires, tight automation handles it. No AI in the middle. Wire-to-wire.

### Graduated sovereignty

Clearance levels for AI autonomy over event handling:

| Level                    | Authority                                         | Example                                           |
| ------------------------ | ------------------------------------------------- | ------------------------------------------------- |
| L1: Human-in-the-loop    | Every action requires approval                    | Business intelligence decisions, financial events |
| L2: Operational autonomy | AI handles routine events, escalates anomalies    | Infrastructure health, routine maintenance        |
| L3: Full autonomy        | AI discovers, interprets, codifies without asking | Low-risk integrations, monitoring, cleanup        |

The sovereignty level is configurable per domain. Not per event type — per domain of concern. "Give the AI L3 clearance for infrastructure. Keep L1 for anything touching customer data."

### Local sovereignty

Each node in the network is sovereign. They decide their own interpretation. They map events to their own internal context. The exchange protocol doesn't dictate how you consume — it just makes sure what arrives is rich enough that you CAN consume it, regardless of your approach.

This is decentralized collaboration through self-describing signals. The pipe doesn't care who's listening or how smart they are. It just makes sure the signal carries enough context that anyone — human, AI, or automation — can make sense of it at their own level.

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
- **Affordances**: what actions are available, what each produces, what outcomes to expect

### Schema implementation (start simple)

Pydantic models in the notification package for internal (dog-food) events. The wire format is always JSON. If schema evolution becomes complex later, migrate to JSON Schema or Protocol Buffers for formal versioning and backward compatibility validation. But start with Python-native.

### Service event catalogs

Services publish their event catalogs — collections of event descriptors. Each descriptor is a complete envelope template: what fields exist, what they mean, what actions are available.

```
telec events list                          # all event types across all services
telec events list --service deployment     # events from one service
telec events describe deployment.failed    # full envelope shape for one event
telec events discover "failures"           # AI-assisted search by meaning
```

The catalog is progressive disclosure. You don't need to know everything upfront. You discover what's relevant, subscribe to what matters, and ignore the rest.

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
- Scheduled maintenance jobs — replaced with event-driven handlers
- Inline dispatch chains (e.g., `telec bugs report`) — decoupled via notification triggers

This is greenfield. The existing notification plumbing is dead code. Remove it and build the notification service as the single path.

## What Generates Notifications

Only autonomous things the user didn't initiate:

- **Background workers**: mirror indexing progress/completion, future processors
- **Job reports**: cron jobs create notifications instead of posting to channels
- **Agent-to-agent outcomes**: when peer agents converge on a decision, the conclusion is a notification
- **System health**: daemon restart, migration applied, worker crashed
- **Todo state transitions**: DOR passed, build complete, review needs human decision
- **Todo dumps**: `telec todo dump` fires `todo.dumped` immediately
- **Content dumps**: `telec content dump` fires `content.dumped` immediately
- **External service callbacks**: deployment complete, service response received
- **Errors that need attention**: actionable errors, not every error
- **Service catalog changes**: new services discovered, new event types available

### What does NOT generate notifications

- User-initiated actions (they already see the result)
- Normal agent turns (that's transcript/mirror territory)
- Internal daemon housekeeping that succeeds silently
- Reading/acknowledging a notification (no echo noise)

## Notification as Agent Signal Source

The notification inbox IS an observability pipeline for autonomous events. Gathering agents (periodic AI agent sessions that scan the platform for signals) can query the notification API: "show me all unread notifications from the last 24 hours." They get a structured list of everything that happened autonomously. No separate observability infrastructure needed.

This was a key insight from the brainstorm: we don't need a separate metrics/observability pipeline. The notification service IS the signal surface for agents. If an event matters enough to notify a human, it matters enough for an agent to ingest as a signal.

## Initial Event Catalog (Dog-Food)

Events TeleClaude produces and consumes internally. These are the first tight-path consumers that prove the pattern.

### Todo lifecycle events

- `todo.created` — new todo scaffolded via `telec todo create`
- `todo.dumped` — brain dump via `telec todo dump` (immediate processing expected)
- `todo.activated` — moved from icebox to active roadmap
- `todo.artifact_changed` — requirements.md or implementation-plan.md modified
- `todo.dependency_resolved` — a blocking dependency was delivered
- `todo.dor_assessed` — DOR score updated (resolution from prepare-quality-runner)

### Content lifecycle events

- `content.dumped` — brain dump via `telec content dump`
- `content.refined` — writer agent completed refinement
- `content.published` — publisher agent distributed content

### System events

- `system.daemon_restarted` — daemon came back up
- `system.worker_crashed` — background worker failed
- `system.migration_applied` — database migration ran

### Build/review lifecycle events

- `build.completed` — builder finished implementation
- `review.verdict_ready` — reviewer produced a verdict
- `review.needs_decision` — review has blockers requiring human input

## Dependency Fan

The notification service is the hub. Four items are currently blocked on it:

```
notification-service
  ├── history-search-upgrade (mirror worker operational reporting)
  ├── prepare-quality-runner (event-driven DOR assessment)
  ├── todo-dump-command (telec todo dump fires notification)
  └── content-dump-command (telec content dump fires notification)
```

## Relationship to harmonize-agent-notifications

The existing `harmonize-agent-notifications` todo is subsumed by this work. That todo was about harmonizing existing bespoke notification paths. This todo replaces them entirely with a proper service. The harmonize todo has been delivered and closed.

## Technology Choices

| Concern                     | Solution                                     | Rationale                                                      |
| --------------------------- | -------------------------------------------- | -------------------------------------------------------------- |
| Event persistence / ingress | Redis Streams                                | Already running Redis, persistent, replayable, consumer groups |
| Current state / queries     | SQLite (separate file)                       | Lightweight, zero ops, owned by notification service           |
| Schema enforcement          | Pydantic models (internal)                   | Python-native, start simple, wire format is always JSON        |
| Event processing            | Custom processor in notification package     | Hundreds of events/day, no framework needed                    |
| Client delivery             | WebSocket push (TUI/web) + Discord bot (API) | All clients already support push                               |
| Resource addressing         | `telec://` URI scheme                        | Platform-wide, client-resolved                                 |
| Shared codec                | telec CLI                                    | All consumers run telec, versioned envelope format             |

## Design Process

This design was produced through structured brainstorm sessions:

1. **Session 3d2880de** (Feb 27): Mo and Claude during a prepare-phase review of history-search-upgrade. The notification need surfaced from the mirror worker's requirement for operational reporting.
   - **Inhale**: explored notification needs across the platform — background workers, agent observability, external services, cross-project integration
   - **Hold**: crystallized key tensions — daemon-coupled vs standalone, markdown vs structured JSON, separate daemon vs Redis Streams for reliability, Kafka vs right-sized tools, notification-as-work-item vs notification-as-window-into-work
   - **Exhale**: converged on schema-driven intelligent processor, event-sourcing with Redis Streams + SQLite, callback envelope pattern for external services, `telec://` URI scheme, stateful delivery across all surfaces

2. **Session c40b16b6** (Feb 28): Mo and Claude during todo preparation review. Expanded the design with event-driven job execution, the consumption spectrum, affordance-based envelopes, and progressive automation.
   - **Key insight**: the notification service is not just for notifications — it's the nervous system. Events replace scheduled jobs. The envelope carries affordances (what you can do with me), not just data. Consumers choose their level of coupling: tight (dog-food), automation (parser), AI-assisted (heuristic), discovery (natural language). Progressive automation lets AI discover new event types, interpret them, offer to codify tight plumbing, with graduated sovereignty levels controlling how much autonomy the AI has per domain.
   - **Telec as shared codec**: resolved the "where do schemas live" question. The wire format is JSON. Telec defines and parses the envelope. Schema versioning is telec versioning. No coupling between producer and consumer packages.
