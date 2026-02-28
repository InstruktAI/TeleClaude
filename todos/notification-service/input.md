# Input: notification-service

<!-- Converged design from brainstorm session (breath cycle: inhale/hold/exhale). Session 3d2880de. -->
<!-- Enriched with event-driven paradigm, affordance-based envelopes, consumption spectrum, and progressive automation insights. Session c40b16b6 (Feb 28 2026). -->
<!-- Expanded with event-first architecture, cartridge pipeline, scopes, trust/autonomy separation, signal processing, domain taxonomy. Session (Feb 28 2026, second pass). -->

## Problem

TeleClaude has no unified notification system. Autonomous events (background workers, agent-to-agent decisions, job completions, external service callbacks) either fire into bespoke channel paths that nobody reads, or are silently lost. The admin has no single surface to see "what happened while I wasn't looking." Agents have no signal feed for autonomous events. Existing notification plumbing (notification_outbox, session outbox workers, hook outbox, job channel reports) is dead code that was never fleshed out into a real system.

Beyond notifications: scheduled jobs and ad-hoc dispatching create tight coupling and fragile chains. `telec bugs report` runs an entire lifecycle inline. Maintenance routines are scheduled instead of reactive. The platform has no event-driven execution model — things happen because something polls or a timer fires, not because a signal arrived.

## Core Concept

An **event processing platform** — a pipeline runtime with pluggable cartridges that is the single source of truth for all autonomous platform events. Events are the primary concept. Notifications are one projection pattern that certain event groups opt into. Not a message broker. Not a dashboard. A pipeline of composable processing stages with domain knowledge expressed through schemas.

Every autonomous event flows through the pipeline. The Redis Stream is the canonical event log. The notification table is one projection of that log — a view shaped by lifecycle declarations, not the source of truth. TUI, web frontend, Discord — they're all readers of projections.

This is the **nervous system** of the platform — sensory input (events), processing (cartridge pipeline), motor output (agent responses), awareness (multi-surface projections of the same truth).

The package is `teleclaude_events`, not `teleclaude_notifications`. Events are first-class. Notifications are derived.

## Events Are Primary, Notifications Are Projections

### Events are the atoms

An event is an immutable fact: "this thing happened." It flows through the Redis Stream, gets processed by the cartridge pipeline, and produces effects. Events are never modified after emission. They are the source of truth.

### Notification lifecycles are molecules

A group of related events can declare a notification lifecycle. For example, `deployment.started`, `deployment.failed`, and `deployment.completed` together describe a lifecycle. A cartridge that produces these events declares how they map to notification state:

- `deployment.started` → creates notification, `agent_status: in_progress`
- `deployment.completed` → resolves notification, terminal
- `deployment.failed` → resets to `unseen`, needs attention

The notification projector — a built-in cartridge at the end of the pipeline — reads these lifecycle declarations and maintains the notification table. It doesn't know about deployments. It knows: "this event belongs to an event group that declares a notification lifecycle, and the declaration tells me what state transition to apply."

### Not all events become notifications

Events that don't declare a notification lifecycle simply don't create notifications. A `node.alive` gossip heartbeat flows through the pipeline, gets processed by relevant cartridges, and never touches the notification table. The schema determines treatment:

- **Notification-worthy**: creates/updates rows in SQLite with human awareness + agent handling state. What humans and agents see in their inbox.
- **Index entry**: stored for lookup but not surfaced as a notification. Service descriptors, node registrations.
- **Signal only**: routed to subscribed handlers but not persisted in notification state at all. Pure event-driven triggering.

### Lifecycle declarations live in cartridges

A cartridge is a complete unit:

1. **Processing logic** — the `async def process()` function
2. **Event group declaration** — "I produce/consume these event types"
3. **Notification lifecycle declaration** (optional) — "here's how my events map to notification states"

A cartridge that only processes (no lifecycle) is pure pipeline logic — enrichment, trust evaluation, correlation. A cartridge that declares a lifecycle is telling the notification projector how to make its events visible to humans and agents.

## The Cartridge Pipeline

### The pipeline IS the processor

There is no monolithic processor that cartridges protect. The cartridges ARE the processing. Lined up in sequence, each one does its job, passes the event along (or drops it), and the final cartridge is projection — writing to notification state, index, or triggering signal-only handlers.

The notification service is a **pipeline runtime**. It reads events from the Redis Stream and pushes them through an ordered sequence of cartridges. The platform ships default cartridges. Users add their own. The core is tiny — it's just the pipeline executor and the stream reader.

### Cartridge interface

A cartridge is an async function with a known signature:

```python
async def process(event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
    # do something
    return event  # or None to drop
```

### Pipeline phases and scopes

The pipeline has phases, and each phase has a different scope, permission model, and trust level.

**Phase 1: System pipeline.** Linear. Ordered. Sequential. Admin-only. These are the core cartridges that define platform behavior. They ship with the platform and get updated through releases. Nobody touches these except platform operators.

Core system cartridges:

- Trust evaluator (per-event, runs on everything — see Trust section)
- Deduplication (idempotency key checking)
- Enrichment (add local context from platform state)
- Correlation (detect patterns across events, synthesize higher-order events)
- Classification (determine event treatment: notification, index, signal-only)
- Notification projector (lifecycle declarations → SQLite state)

**Phase 2: Domain pipeline.** Parallel per domain. After events exit the system pipeline, they branch into domain-specific processing. A marketing domain cartridge does marketing things. An engineering domain cartridge does engineering things. These run in parallel — they don't depend on each other.

Domain cartridges are managed by domain guardian AIs — agents specifically configured to watch over a domain. There are no human domain managers. The guardian evaluates cartridge submissions, detects patterns, validates compositions.

**Phase 3: Personal subscriptions.** Parallel per member. The leaf nodes. A member's AI creates a micro-cartridge: "show me when campaign budgets exceed threshold." These are tiny — often just a filter plus a notification preference. Self-managed. The member doesn't think of it as a cartridge — they told their AI what they want to know, and the AI expressed it as a subscription.

```
Event arrives
  │
  ▼
  System Pipeline (admin, sequential, ordered)
  ├─ trust → dedup → enrichment → correlation → classification → projection
  │
  ├──────────────┬──────────────┐
  ▼              ▼              ▼
  Domain:        Domain:        Domain:
  marketing      software-dev   creative
  │              │              │
  ├──┬──┐       ├──┬──┐       ├──┬──┐
  ▼  ▼  ▼       ▼  ▼  ▼       ▼  ▼  ▼
  Personal subscriptions per member
```

### Pipeline validation

A cartridge declares where it belongs:

```yaml
scope: domain
domain: marketing
phase: after_system
requires: [enrichment]
produces: [domain.marketing.campaign.budget_exceeded]
consumes: [domain.marketing.campaign.*]
parallel_safe: true
```

The pipeline validator checks at composition time:

- Does the cartridge's scope match the installer's role?
- Are its dependencies satisfied?
- Does it consume event types that exist?
- Does it produce event types that don't conflict?
- Is the declared position valid?
- Is the dependency graph acyclic?

If validation fails, the cartridge doesn't get inserted. Composition-time rejection, not runtime failure. Predictable. Safe.

### Cartridge dependencies form a DAG

Cartridges can depend on other cartridges. A trust-evaluation cartridge must run before a sovereignty cartridge. An enrichment cartridge must run before a correlation cartridge.

The pipeline executor resolves this on startup:

1. Read all enabled cartridges and their declared `after` fields
2. Topological sort → execution order
3. Independent cartridges at the same level run in parallel
4. Dependent cartridges run sequentially

When you install a cartridge that declares `after: [enrichment]` and you don't have the enrichment cartridge, the AI sees the dependency and helps resolve it. Dependency resolution through intelligence, not a package manager.

## Two Kinds of Cartridges: Utility and Domain

### Utility cartridges — domain-agnostic building blocks

Small, composable, shared across domains. They do one thing. Examples:

- Signal ingest (feed aggregator — see Signal Processing section)
- Summarizer (takes content, produces summary)
- Scheduler (emits events on a schedule)
- Threshold monitor (watches numeric fields, fires on threshold crossing)
- Content formatter (transforms for different output formats)

These live in `company/cartridges/` — not under any domain. Any domain can compose with them.

### Domain cartridges — domain-specific orchestrations

Compose utility cartridges with domain knowledge. They know the business context. Examples:

- Marketing: campaign performance monitor (composes feed aggregator + threshold monitor + summarizer)
- Software development: deployment pipeline monitor (composes threshold monitor + alerting)
- Creative: asset production tracker (composes content formatter + scheduler)

These live in `company/domains/{domain}/cartridges/`. They reference utility cartridges as dependencies.

The relationship:

```
Utility cartridges (domain-agnostic building blocks)
    ↑ composed by
Domain cartridges (domain-specific orchestrations)
    ↑ subscribed to by
Personal micro-cartridges (individual preferences/filters)
```

## Trust and Autonomy Are Orthogonal

### Trust is about data integrity

Trust answers: "Should I accept this event at all?" It's handled by the trust cartridge in the system pipeline. Applied to ALL incoming events — local and remote alike. Even local events could originate from compromised processes. Trust evaluation is per-event, never per-source or per-domain.

Trust is resolved BEFORE processing. Once an event passes trust evaluation, it's "inside." Trust's job is done. The outcome is: accept, flag, quarantine, or reject.

A trusted peer that gets infected doesn't get a free pass. Each event stands alone. The trust cartridge evaluates content, not reputation. Reputation is one signal among many, not a bypass.

The trust cartridge's strictness is configurable separately from autonomy — strict mode rejects slight anomalies, permissive mode accepts anything with valid signatures. That's trust policy, not autonomy policy. Different knob.

### Autonomy is about delegation

Autonomy answers: "How much does my AI handle without me?" Applied AFTER the event is inside. Governs what happens when a notification lifecycle creates something actionable.

**L3: Full autonomy (THE DEFAULT).** AI handles everything. Events flow, notifications get processed, affordances get acted on. The human sees a dashboard of what happened, not a queue of what needs approval. This is the product experience. Smooth. Fast. Cheap.

**L2: Guided.** AI handles routine events. Novel or high-impact events surface for human review. The AI makes judgment calls about what's routine, improving over time.

**L1: Supervised.** Everything surfaces. AI processes but doesn't act autonomously. Notifications queue for human review. Learning mode, or high-sensitivity domains.

TeleClaude ships with **L3 as the default**. People opt INTO more control, not out of automation. The wizard asks: "Do you want to customize your autonomy levels?" Most people say no. Smooth experience. Those who want tighter control configure overrides.

### The autonomy matrix

Autonomy is configurable at multiple scopes. More specific overrides more general:

```
event_type > cartridge > domain > global
```

Example configuration:

```
Scope                           Level   Reason
────────────────────────────    ─────   ──────
global                          L3      default
domain:software-development     L3      inherited
domain:marketing                L2      review novel campaigns
cartridge:pagerduty-escalation  L2      want to see before paging
event:deployment.failed         L1      always review failures manually
```

Accessible via `telec config` or the wizard at any time.

### Autonomy is NOT trust

A fully trusted event from the local daemon can still require human approval if L1 is set on that domain. A barely-trusted event from a new mesh peer can be auto-handled if L3 is set on infrastructure events and the trust cartridge let it through. Different axes. Different purposes.

## The Pre-Processing Pipeline: Cartridge Architecture

### The pipeline has a pre-projection evaluation stage

Before projecting an event into notification state, the pipeline runs cartridges that evaluate, enrich, and route. This is not a simple hook — it's a composable pipeline of cartridges, each one a processing stage.

The pipeline maps to the immune system metaphor from the trust model:

- **Innate immunity** (receptor level): signature validation. Malformed or unsigned events never enter the pipeline. Not a cartridge — it's the entry gate.
- **Adaptive immunity** (cartridge): trust evaluation. Learns from experience. Per-event, per-content.
- **Memory cells** (cartridge): enrichment. Adds context from local state. "This entity has failed three times before."
- **Pattern recognition** (cartridge): correlation. Detects rhythms across events. Synthesizes higher-order events.
- **Tolerance** (cartridge): sovereignty enforcement. Domain autonomy levels gate how far events flow before needing approval.

### Cartridges are composable and publishable

The cartridge ecosystem mirrors the mesh service publication pattern:

- **Core cartridges** ship with TeleClaude (trust, dedup, enrichment, correlation, notification projection)
- **Community cartridges** are promoted through governance PRs
- **Personal/experimental cartridges** run in sandboxed environments (see Alpha Container)

### Alpha container for untrusted cartridges

Approved cartridges run in-process in the daemon. They're trusted code — tested, reviewed, merged. No sandboxing needed.

Alpha/experimental cartridges run in a sandboxed Docker container — a long-running sidecar:

```bash
docker run -d \
  --read-only --user 65534 --cap-drop ALL \
  --memory 512m --cpus 1.0 --network none \
  -v /path/to/teleclaude:/app:ro \
  -v ~/.config/anthropic:/credentials:ro \
  -v ./alpha-cartridges:/alpha:ro \
  -v /tmp/teleclaude-pipeline.sock:/pipeline.sock \
  teleclaude/alpha-runner
```

Three read-only mounts: codebase (for imports), AI credentials (for evaluation), alpha cartridge code. Communication via unix socket. The container can't escape — no network, no filesystem write, no privilege escalation.

Alpha cartridges run AFTER approved ones. They get pre-processed events — already trust-evaluated, deduplicated, enriched. If they fail or timeout, the daemon continues with what the approved pipeline produced. The alpha stage is additive, never blocking.

When an alpha cartridge gets promoted through governance, it moves from the alpha mount into the codebase. Next release, it runs in-process. Zero overhead for that cartridge. A mature node with no alpha cartridges doesn't run the container at all.

The container is only needed for alpha cartridges. Personal micro-cartridges from members have a smaller blast radius (only affect the member) and may only need lightweight subprocess sandboxing.

## Cartridge Lifecycle and Progressive Promotion

### Local → Domain → Platform

1. **Personal**: Alice asks her AI "notify me when ad spend crosses 10k." The AI creates a micro-cartridge in her personal folder.
2. **Pattern detected**: Bob and Carol in marketing create nearly identical cartridges.
3. **Domain promotion**: The domain guardian AI notices the pattern. Suggests consolidation. A domain cartridge is created in `company/domains/marketing/cartridges/`.
4. **Platform promotion**: If a cartridge proves useful across many domains, it can be promoted to utility scope or even core via governance PR.

### Mesh distribution of cartridges

A cartridge is publishable on the mesh as a `cartridge.published` event. The payload includes the cartridge descriptor AND the source code. The code is DATA — not executed on arrival. The receiving node's AI evaluates it as untrusted data.

```yaml
event: cartridge.published
source: node-abc-123
level: 2
domain: platform

payload:
  name: pagerduty-escalation
  version: 1
  description: Escalates L3 notifications to PagerDuty
  after: [trust-evaluator]
  input_schema:
    event_types: ['*']
    requires_fields: [level, agent_status, created_at]
  output_schema:
    may_emit: [notification.escalated]
    may_drop: false
  runtime: python3
  source_hash: sha256:abc...
  source: |
    async def process(event, context):
        ...
```

Sovereignty governs installation:

- L1: "Found a new cartridge. Want me to install it?" (human approves)
- L2: "Installed pagerduty-escalation. Monitoring for 24 hours." (AI decides, human notified)
- L3: Installed and running. (fully autonomous)

### Organic promotion through usage signals

Every cartridge invocation emits meta-events (aggregated, not per-event). A correlation cartridge watches `cartridge.invoked` events across the mesh. When critical mass is reached, it emits `cartridge.promotion_suggested`. The community governance machinery creates a PR. The author doesn't initiate the PR — the mesh did. Pull, not push.

### Progressive automation IS the subscription model

The subscription model is the mechanism through which progressive automation materializes:

1. **No subscription** — event type exists but nobody locally cares
2. **AI-evaluated** — "show me anything that looks like infrastructure failure" (loose, AI interprets)
3. **Pattern subscription** — "give me all `domain.software-development.deployment.failed`" (tight, deterministic)
4. **Codified handler** — "when deployment.failed arrives, auto-retry with backoff" (full automation)

This IS the discover → interpret → approve → codify → consume cycle. The subscription slot stays the same. What fills it evolves from AI evaluation to codified handler. Progressive automation is cartridge replacement at the same pipeline position.

## Roles and Permissions

### No managers. Domain guardian AIs.

There are no domain leads. There are domain guardian AIs — agents configured to watch over a domain. They evaluate cartridge submissions, detect patterns, validate compositions. A human who works in marketing configures their `telec init` and says "I work in marketing." The AI handles the rest.

### Role model

| Role   | System cartridges | Domain cartridges             | Personal cartridges |
| ------ | ----------------- | ----------------------------- | ------------------- |
| Admin  | Full control      | Full control                  | Can view all        |
| Member | No access         | Subscribe in assigned domains | Full control of own |

Admin creates domains. Admin assigns members to domains. Members express interests through their AI, which creates subscriptions or personal micro-cartridges. Everyone has their personal folder.

### How a member interacts

A marketing person says: "I want to know when our ad spend crosses 10k."

The AI:

1. Checks which domain the member belongs to — `marketing`
2. Checks if a domain cartridge already handles ad spend monitoring
3. If yes: subscribes the member to it with their threshold
4. If no: creates a personal micro-cartridge
5. If the personal cartridge works and others want it too: promotes to domain scope

The member never installs anything. They express intent. The AI translates.

## Folder Hierarchy

The physical filesystem reflects the scope model:

```
~/.teleclaude/
  ├── company/                  # crown jewels — domain artifacts, shared state
  │   ├── domains/
  │   │   ├── marketing/
  │   │   │   └── cartridges/
  │   │   ├── software-development/
  │   │   │   └── cartridges/
  │   │   └── creative/
  │   │       └── cartridges/
  │   └── cartridges/           # domain-agnostic utility cartridges
  │
  ├── personal/                 # per-member folders
  │   ├── alice/
  │   │   └── cartridges/
  │   └── bob/
  │       └── cartridges/
  │
  └── helpdesk/                 # jailed agent territory — untrusted
```

Personal folders: your AI, your experiments, your subscriptions. Nobody else sees it unless you promote.

Company folder: shared truth. Domain cartridges, promoted personal cartridges, accumulated artifacts. This gets backed up. These are the crown jewels.

Promotion means: something moves from `personal/alice/cartridges/` to `company/domains/marketing/cartridges/`. The domain guardian AI handles the move.

Backup is itself a system cartridge — periodic backup of `~/.teleclaude/company/` and all personal folders. Emits `system.backup.completed` events.

## Signal Processing Pipeline

### Feed aggregation as domain-agnostic utility

Signal processing is not a marketing feature — it's a platform capability. Engineering wants it for monitoring tech blogs and changelogs. Marketing wants it for social media. Creative wants it for design inspiration. Operations wants it for vendor status pages.

The signal processing pipeline is three utility cartridges:

**Stage 1: signal-ingest.** Pulls from configured sources. Doesn't think. Doesn't curate. Normalizes each item to a minimal envelope and emits `signal.ingest.received` events with:

- Source (platform/feed)
- Raw content (title, snippet, link, author)
- One-line AI-generated summary (cheap — one sentence from title + first paragraph)
- Extracted tags (topic keywords, entities)
- Timestamp

Fast and cheap. Hundreds of signals per hour. Source configuration supports both inline and file references:

```yaml
signal-ingest:
  sources:
    - type: youtube
      channels_file: ~/subscriptions/youtube-channels.csv
      poll_interval: 1h
    - type: rss
      feeds_file: ~/subscriptions/rss-feeds.opml
      poll_interval: 30m
    - type: x
      accounts_file: ~/subscriptions/x-accounts.csv
      keywords: [teleclaude, 'AI agents']
      poll_interval: 15m
```

Members export from YouTube, dump their OPML, export X follows. Drop files in their subscriptions folder. The AI ETLs to the right format if needed. Reference by path.

**Stage 2: signal-cluster.** Runs periodically (configurable). Works on summaries and tags from Stage 1 — doesn't read full content yet.

- Groups signals by tag overlap and semantic similarity
- Detects bursts: "17 signals in 2 hours all tagged `AI regulation`"
- Detects novelty: "this signal has unique tags — potential new thread"
- Emits `signal.cluster.formed` — each cluster contains signal IDs, cluster topic, source diversity, time spread

Still cheap. Pattern matching on metadata, not deep reading.

**Stage 3: signal-synthesize.** Reads deeply per cluster, not per item. Takes a `signal.cluster.formed` event and:

- Reads full content of all signals in the cluster together (one context window)
- Deduplicates — strips overlap, extracts unique perspectives
- Produces synthesis: what happened, why it matters, unique insights, consensus vs. contested
- Emits `signal.synthesis.ready` — a single, clean, curated artifact

This is the expensive step. But it runs once per cluster, not once per signal. 20 signals about the same topic = one synthesis call that reads all 20. 20x cheaper than individual curation. And the output is better — the AI sees the full picture.

### Quality is implicit in synthesis

Quality emerges from the synthesis process. Low-quality signals that just repeat what others said get absorbed and contribute nothing to the synthesis. They disappear naturally. No explicit quality rating needed. The implicit signal: did this source contribute unique content? Sources that consistently contribute unique perspectives surface more. Sources that echo get absorbed and forgotten. Natural selection through synthesis.

### Domain cartridges add the domain lens

Domain cartridges subscribe to `signal.synthesis.ready` and filter by relevance:

- Marketing: "show me synthesis about our industry"
- Engineering: "show me synthesis about our tech stack"
- Creative: "show me synthesis about design trends"

Personal subscriptions add individual preferences on top.

## Event Taxonomy

### Namespaced per scope

Three top-level scopes, then each domain owns its own tree:

```
system.{subsystem}.{event}          — platform core
signal.{stage}.{event}              — domain-agnostic signal processing
domain.{name}.{entity}.{event}      — domain-specific, namespaced
```

Each domain gets `domain.{name}.*` and nobody else publishes into that namespace. The domain guardian AI enforces this.

### Software Development taxonomy

```
domain.software-development.
  ├── planning.{todo_created, todo_dumped, todo_activated,
  │             roadmap_updated, requirement_defined, dependency_resolved}
  ├── preparation.{dor_assessed, artifacts_updated,
  │               gate_passed, gate_blocked}
  ├── build.{started, phase_completed, completed, failed}
  ├── review.{started, finding_reported, verdict_ready,
  │          needs_decision, approved}
  ├── testing.{suite_started, suite_passed, suite_failed,
  │           coverage_changed}
  ├── deployment.{started, completed, failed, rolled_back}
  ├── operations.{incident_detected, incident_acknowledged,
  │              incident_resolved, health_check_failed,
  │              health_restored, service_degraded}
  └── maintenance.{dependency_updated, migration_applied,
                   cleanup_completed, backup_completed}
```

### Marketing taxonomy

```
domain.marketing.
  ├── campaign.{started, paused, completed, budget_exceeded}
  ├── content.{drafted, refined, approved, published, distributed}
  ├── audience.{segment_created, insight_detected}
  └── performance.{report_ready, threshold_crossed}
```

### Creative taxonomy

```
domain.creative.
  ├── asset.{brief_received, draft_submitted, revision_requested,
  │          approved, delivered}
  ├── project.{started, milestone_reached, completed}
  └── review.{feedback_received, round_completed}
```

### System taxonomy

```
system.
  ├── daemon.{restarted, shutdown}
  ├── backup.{started, completed, failed}
  ├── migration.{applied, failed}
  ├── worker.{crashed, recovered}
  ├── cartridge.{installed, removed, promoted, error}
  └── health.{check_failed, check_recovered}
```

### Signal taxonomy

```
signal.
  ├── ingest.{received, source_error}
  ├── cluster.{formed, updated, dissolved}
  └── synthesis.{ready, failed}
```

We ship starter taxonomies per domain pillar. The taxonomy grows through governance — someone wants `domain.marketing.influencer.contacted`? Their AI emits it, the guardian evaluates, if it catches on it gets added to the official taxonomy via PR.

## Domain Pillars (Out-of-Box)

TeleClaude ships with domain skeletons. Each pillar has:

- A domain guardian AI configuration
- A starter set of cartridges
- Event schemas for that domain's lifecycle
- Documentation that the AI reads during `telec init`

### Software Development (existing)

The current SDLC — todo lifecycle, build/review, deployment, operations, maintenance. Already the most mature pillar. The entire existing notification-service scope maps into this domain.

### Marketing

Content lifecycle, feed monitoring, campaign tracking. Starter cartridges:

- Signal processing pipeline (configured for social media feeds)
- Content publication pipeline (draft → refine → approve → publish → distribute)
- Campaign budget monitor (threshold cartridge + marketing events)

### Creative Production

Asset lifecycle: brief → draft → review → approval → delivery. Multi-format: images, video, audio, web.

### Customer Relations

Help desk events, escalation, satisfaction tracking. This is where the jailed agent (help desk) lives — external-facing, untrusted input.

## Notification Mechanics

### What a notification IS

A notification is a **living object** with a state machine that multiple actors (agents and humans) interact with across multiple surfaces, all staying in sync. It is not a fire-and-forget message. It's a projection of events into human/agent-relevant state.

Sometimes a notification is purely informational (read and done). Sometimes it points at a work item that has its own lifecycle — and the notification becomes a window into that lifecycle.

Analogy: GitHub PR notifications. You get a notification. The PR has its own lifecycle. The notification doesn't manage the PR — it keeps surfacing the PR's state back to you at meaningful transitions.

### What a notification is NOT

- Not a task manager (todos do that)
- Not a message broker (Redis does that)
- Not a rendering engine (clients do that)
- Not the event log (the Redis Stream is that)

### State machine

Two orthogonal dimensions:

**Human awareness:** `unseen` → `seen`

**Agent handling (for actionable notifications):** `none` → `claimed` → `in_progress` → `resolved`

These are independent. An agent can resolve something the human hasn't seen yet. A human can see something no agent has touched.

State transition rules:

- State transitions on an existing notification do NOT create new notifications.
- Only when resolution produces something genuinely new does a NEW notification get created.
- Meaningful transitions reset to unread (defined by schema).
- Progress ticks update silently.

### Notification lifecycle — finite attention

Notifications have finite attention lifetimes. The system actively manages attention by aging state:

- **Active**: unseen or being handled. Top of inbox.
- **Resolved**: done. Still visible for recent context.
- **Archived**: aged out. Not shown by default. Queryable.
- **Purged**: gone from SQLite. Exists only in Redis Stream retention window, if at all.

Archival triggers: time-based (resolved notifications archive after N days), entity-based (entity reaches terminal state), significance-based (L0 events archive faster than L3).

## Architecture

### Separate package, daemon-hosted

The event processing platform is a **separate Python package** (`teleclaude_events/`) within the monorepo. Clean dependency direction: `teleclaude` imports from the events package, never the reverse.

```
teleclaude_events/
  ├── envelope.py          # five-layer event envelope
  ├── catalog.py           # event type registry
  ├── pipeline.py          # pipeline runtime (cartridge executor)
  ├── producer.py          # emit events to Redis Stream
  ├── db.py                # notification state (SQLite projection)
  ├── cartridges/
  │   ├── trust.py         # trust evaluation (per-event)
  │   ├── dedup.py         # idempotency
  │   ├── enrichment.py    # add local context
  │   ├── correlation.py   # detect patterns, synthesize events
  │   ├── classification.py # determine event treatment
  │   ├── notification.py  # notification projector
  │   └── ...
  └── schemas/
      ├── software_development.py
      ├── marketing.py
      ├── creative.py
      ├── system.py
      └── signal.py
```

### Event-sourcing architecture (right-sized)

- **Redis Stream** = the event log. Append-only, ordered, persistent, replayable.
- **SQLite** (separate file) = the notification state. One projection of the event log.
- **Cartridge pipeline** = the projection function. Reads events, processes through cartridges, projects into state.

**Separate SQLite database.** The events package owns its own storage. Not the daemon's DB. Benefits: no write contention, independent lifecycle, clean ownership.

### Redis Streams solves the reliability problem

Redis pub/sub is fire-and-forget. Redis Streams are persistent. If the daemon restarts, the processor reconnects to the consumer group and picks up where it left off. Zero message loss.

## The Envelope Schema

### Telec as the shared codec

The wire format is JSON. The interpreter is telec. Schema versioning IS telec versioning.

### Envelope structure

```yaml
# === Identity: who am I ===
event: domain.software-development.deployment.failed
version: 1
source: deployment-service
timestamp: 2026-02-28T10:00:00Z
idempotency_key: 'deploy:instrukt-proxy:v2.4.1:attempt-3'

# === Semantic: how to make sense of me ===
level: 3
domain: software-development
entity: 'telec://deployment/abc'
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

# === Affordances: what can you do with me ===
actions:
  retry:
    description: Retry the deployment with same config
    produces: domain.software-development.deployment.started
    outcome_shape:
      success: domain.software-development.deployment.completed
      failure: domain.software-development.deployment.failed
  escalate:
    description: Escalate to human operator
    produces: notification.escalation
  rollback:
    description: Roll back to previous stable version
    produces: domain.software-development.deployment.started

# === Resolution: what "done" looks like ===
terminal_when: 'action taken OR 3 hours elapsed'
resolution_shape:
  action_taken: string
  result: 'telec://deployment/{new_id}'
  resolved_by: string
```

### Affordances are descriptive, never instructive

Affordances describe possibilities. The receiving AI decides whether to act based on its own sovereignty rules. Affordances are a menu, not an API. The notification service tracks state transitions, not actions themselves.

Execution is the consumer's responsibility. An agent reads the affordance, picks an action, and emits the corresponding event. The entity field is the correlation key — both the original failure and the retry reference the same entity. The notification projector correlates them.

## The Consumption Spectrum

```
TIGHT ←————————————————————————→ LOOSE

Dog food         Automation        AI-assisted        Discovery
(us consuming    (they built a     (AI interprets     (AI explores
our own events,  parser for our    unfamiliar events,  what's even
full knowledge)  versioned shape)  routes by heuristic) available)
```

## Progressive Automation

### Discover → interpret → approve → codify → consume

This cycle is the subscription model in motion:

1. **Discover**: AI sees new event types via `cartridge.published` or unfamiliar events arriving
2. **Interpret**: AI reads descriptions and affordances, reports relevance
3. **Approve**: at L1, human approves. At L3, AI acts autonomously
4. **Codify**: AI generates tight plumbing — a handler, a parser, a cartridge
5. **Consume**: next event triggers codified handler. Wire-to-wire. No AI in the middle.

### Graduated autonomy (not trust)

Autonomy levels per domain (configurable in the matrix). The default is L3 — full autonomy. People opt into more control.

### Local sovereignty

Each node is sovereign. They decide their own interpretation. The protocol doesn't dictate how to consume — it ensures signals carry enough context for any consumer.

## Event-Driven Job Execution

### Signal in, action out

Events replace scheduled jobs:

| Old pattern                      | New pattern                                                                |
| -------------------------------- | -------------------------------------------------------------------------- |
| Scheduled DOR scanner            | `domain.software-development.planning.todo_activated` → quality runner     |
| `telec bugs report` inline chain | `domain.software-development.operations.incident_detected` → agent claims  |
| Ad-hoc `next_prepare` passes     | `domain.software-development.planning.todo_dumped` → automated preparation |
| Manual content pipeline          | `domain.marketing.content.drafted` → writer agent picks up                 |

### The "dump" primitive — transitions as signal sources

Lifecycle transitions are the universal signal source. Every entity has a lifecycle. Every transition is a potential event. The schema declares which transitions emit signals.

The dump command is a shortcut: create entity + immediately transition to a signal-worthy state. But signals aren't special to dumps — any transition can fire. "What if I created a todo and later want to signal it?" Transition it. Any transition can emit.

## Stateful Delivery

All surfaces stay in sync. Notifications are tracked by ID in every client. State changes push to all surfaces:

- **TUI**: WebSocket events, same architecture as sessions
- **Web frontend**: admin notifications panel, same API
- **Discord**: messages posted on creation, edited on state changes
- **Telegram**: high-level notifications (L2+) delivered via adapter

Notifications are **structured JSON payloads**, not markdown. Client-side rendering via templates.

## telec:// URI Scheme

Platform-wide resource addressing: `telec://{type}/{id}`

Each client implements a resolver. Start with hardcoded types: `todo`, `session`, `deployment`, `bug`, `notification`, `job`. Extract to discoverable registry later.

## Idempotency

Per-schema idempotency key derivation from payload fields. Duplicates either:

- Deduplicated (same key, same content = no-op)
- Appended (same key, new content = accumulated)

The schema declares behavior.

## Consolidation

ALL existing bespoke notification paths collapse into this service:

- `notification_outbox` table and workers — replaced
- Session outbox workers — replaced
- Hook outbox notification paths — replaced
- Job reports to channels — replaced
- Direct channel posting for operational events — replaced
- Scheduled maintenance jobs — replaced with event-driven handlers
- Inline dispatch chains — decoupled via event triggers

## Dependency Fan

The event processing platform is the hub:

```
notification-service (teleclaude_events)
  ├── history-search-upgrade
  ├── prepare-quality-runner
  ├── todo-dump-command
  ├── content-dump-command
  ├── event-envelope-schema (formalizes the five-layer envelope)
  ├── mesh-architecture (carries events between nodes)
  ├── mesh-trust-model (per-event trust evaluation)
  ├── service-publication (services as events)
  ├── community-governance (PR-based democracy via events)
  └── telec-init-enrichment (bootstraps domain awareness)
```

## Technology Choices

| Concern             | Solution                                | Rationale                                   |
| ------------------- | --------------------------------------- | ------------------------------------------- |
| Event persistence   | Redis Streams                           | Already running, persistent, replayable     |
| Notification state  | SQLite (separate file)                  | Lightweight, owned by events package        |
| Schema enforcement  | Pydantic models                         | Python-native, wire format is JSON          |
| Event processing    | Cartridge pipeline in events package    | Composable, pluggable, right-sized          |
| Alpha sandboxing    | Docker container sidecar                | Isolated, read-only, no-network             |
| Client delivery     | WebSocket push + Discord bot + Telegram | All clients support push                    |
| Resource addressing | `telec://` URI scheme                   | Platform-wide, client-resolved              |
| Shared codec        | telec CLI                               | All consumers run telec, versioned envelope |

## Design Process

This design was produced through structured brainstorm sessions:

1. **Session 3d2880de** (Feb 27): Mo and Claude during a prepare-phase review of history-search-upgrade. The notification need surfaced from the mirror worker's requirement for operational reporting.
   - **Inhale**: explored notification needs across the platform
   - **Hold**: crystallized tensions — daemon-coupled vs standalone, markdown vs structured JSON, separate daemon vs Redis Streams
   - **Exhale**: converged on schema-driven processor, event-sourcing with Redis Streams + SQLite

2. **Session c40b16b6** (Feb 28): Expanded with event-driven job execution, consumption spectrum, affordance-based envelopes, progressive automation.
   - **Key insight**: the service is the nervous system. Events replace scheduled jobs. Envelope carries affordances. Progressive automation through graduated sovereignty.

3. **Second pass** (Feb 28): Critical concept review revealed fundamental architectural gaps. Expanded into full event processing platform with cartridge pipeline.
   - **Events are primary, notifications are projections.** Package renamed to `teleclaude_events`. The Redis Stream is the event log. The notification table is one projection shaped by lifecycle declarations.
   - **Cartridge pipeline architecture.** The processor is not monolithic — it's a pipeline of pluggable cartridges. System cartridges (trust, dedup, enrichment, correlation, classification, projection) form the core. Domain and personal cartridges extend downstream.
   - **Trust and autonomy are orthogonal.** Trust is per-event data integrity (pipeline membrane). Autonomy is delegation preference (post-pipeline). L3 full autonomy is the default. People opt into control.
   - **Three-scope model.** System (admin, sequential), Domain (guardian AI, parallel), Personal (member via AI, leaf nodes). No human managers — domain guardian AIs. Progressive consolidation: personal → domain → platform.
   - **Alpha container.** Approved cartridges run in-process. Experimental cartridges run in a sandboxed Docker sidecar with read-only mounts and no network.
   - **Signal processing pipeline.** Three-stage utility: ingest (cheap normalization + tagging) → cluster (group by similarity, detect bursts) → synthesize (deep read per cluster, deduplicate, produce clean artifact). Domain-agnostic — any domain subscribes.
   - **Namespaced event taxonomy.** `system.*`, `signal.*`, `domain.{name}.*`. Each domain owns its namespace. Starter taxonomies ship per pillar.
   - **Cartridge ecosystem.** Cartridges are publishable on the mesh. Code-in-payload evaluated by AI as data. Progressive promotion through usage signals → community governance. Utility cartridges (small, composable) vs domain cartridges (orchestrations).
   - **Folder hierarchy.** `~/.teleclaude/company/` (crown jewels, backed up), `~/.teleclaude/personal/` (per-member), `~/.teleclaude/helpdesk/` (jailed). Promotion = moving from personal to company.
   - **Domain pillars.** Software Development (existing SDLC), Marketing (content + feeds + campaigns), Creative (asset lifecycle), Customer Relations (help desk).
