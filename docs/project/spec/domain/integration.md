---
id: project/spec/domain/integration
type: spec
domain: software-development
scope: project
visibility: public
delivered_by:
  - v2-integration
  - v2-integration-cutover
description: Integration bounded context — true external boundaries. Inbound HTTP
  webhooks from third-party providers (Telegram, Discord, WhatsApp, GitHub) and outbound
  delivery to those same providers. Agent CLI hook reception lives in agent_runtime,
  not here.
---

# Integration Domain Spec — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md
- @docs/project/design/architecture-v2/transport-rules.md

## What it is

The `integration` bounded context owns true external boundaries — inbound from and outbound to systems we do NOT control. Inbound HTTP webhooks from third-party providers (Telegram, Discord, WhatsApp, GitHub), outbound delivery to those same providers. Per `transport-rules.md`, the change-axis test places these here because their protocol/format is controlled by the external provider.

Agent CLI hooks are NOT integration's domain — they're in `agent_runtime`. The agent CLI is a system we control (we supervise, we deploy its config, we own its hook receiver `telec-hook`). When the agent CLI hook format changes, `agent_runtime` changes; when Telegram's webhook format changes, `integration` changes. Different axes, different contexts.

Domain services subscribe to integration's events to react; they never deal with transport. Integration provides the durable inbox/outbox pattern that makes external interactions safe across restarts, retries, and provider degradation. For true external events, this gives audit + replay capabilities.

This context does NOT own: domain business rules (each domain service owns its rules — integration just normalizes inputs and dispatches), live session orchestration (`agent_runtime`), agent CLI hook reception (`agent_runtime`), workflow state (`workflow`), knowledge curation (`knowledge`).

## Canonical fields

### Ubiquitous language

**Inbound**
: External (third-party, non-control) system reaching INTO the platform via HTTP webhook (provider POSTs to our endpoint). Agent CLI hooks are NOT integration's concern — those are in agent_runtime.

**Outbound**
: Anything going OUT to an external system. Currently messaging providers (Telegram, Discord, WhatsApp, email).

**Webhook**
: An HTTP POST from an external provider hitting one of our endpoints. Carries provider-specific payload + signature for verification.

**Provider**
: A third-party external system the platform integrates with: Telegram, Discord, WhatsApp, email, GitHub. Each provider has a boundary module that knows its protocol. Agent CLIs are NOT providers — they're internal systems supervised by agent_runtime.

**Provider boundary module**
: The integration code that owns one provider's protocol details: verification, challenge handling, replay/idempotency extraction, payload parsing. Lives at `crates/integration/src/providers/<name>.rs`. MUST NOT import deployment or customer-relations modules.

**Inbox**
: The durable capture of inbound events. Stored in Postgres (`integration.inbox`). Every inbound event lands here first; publication happens after durable capture. Ensures no loss across restarts.

**Outbox**
: The durable queue of outbound deliveries. Stored in Postgres (`integration.outbox`). Producers write to the outbox atomically with their state change; a dispatcher worker delivers asynchronously with at-least-once semantics.

**Dispatcher**
: A worker process draining the outbox. Reads pending entries, attempts delivery via the appropriate channel adapter, marks success or retries. Lives in a `worker-integration` binary the daemon spawns.

**Dead-letter queue (DLQ)**
: Entries that exhausted their retry budget without success. Stored separately (`integration.dlq`). Operators inspect and act manually.

**Channel cascade**
: Per-recipient ordered list of messaging channels to attempt for outbound delivery. Tried in order; advance on failure; email is always the final fallback.

**Recipient**
: A person (or principal) receiving outbound delivery. Identified by their email; the cascade is derived from the person's configured preferences in identity.

**Notification subscription** (per glossary)
: Per-recipient declared interest in receiving certain event categories. Admins are subscribed by default to above-threshold events; non-admins require explicit subscription entries.

**Unreachable record**
: An outbox entry whose entire channel cascade exhausted without success. Recorded with per-channel failure context for operator triage.

**Allowlist**
: The set of event names declared by a provider AND accepted by at least one consumer. Inbound publication is fail-closed: events not on the allowlist are rejected at the boundary with no payload emission.

**Cluster visibility** (per event-bus-transports)
: Integration emits inbound events at `visibility=CLUSTER` because they cross bounded-context boundaries. The unified event bus's CLUSTER publication path is mandatory for inbox.

**Verification challenge**
: A handshake mechanism some providers (WhatsApp/Meta) use to validate the webhook endpoint at registration time. Integration handles the challenge transparently without publishing any domain event.

### Aggregates

#### Inbox Entry (aggregate)

- **Root:** `InboxEntry`
- **Contains:** `entry_id` (UUID), `provider` (telegram, discord, whatsapp, email, github — third-party only), `event_name` (resolved to the canonical event name per provider rules), `payload` (raw, validated), `received_at`, `verified` (bool), `publication_status` (`pending`, `published`, `rejected`), `rejection_reason` (nullable), `idempotency_key`.
- **Invariants:**
  - Every verified inbound event lands here BEFORE publication (durable-first per the inbox posture).
  - Idempotency_key dedupes duplicate provider deliveries (e.g., GitHub may retry); duplicates land but produce no second publish.
  - Publication_status transitions: pending → (published | rejected). Forward only.
  - Rejected entries (allowlist failure, verification failure) are retained for operator inspection but never published.
  - Provider boundary modules write directly; no shared writer.
- **Identifier:** `entry_id`.
- **Lifecycle:** Created by a provider boundary module on inbound. Status advances as the dispatcher publishes (or rejects). Persists for an operator-tunable retention window.

#### Outbox Entry (aggregate)

- **Root:** `OutboxEntry`
- **Contains:** `entry_id` (UUID), `producer_context` (the source bounded context), `event_name` (the producer's domain event), `recipient_email`, `cascade` (ordered channel list), `attempt_count` (per current channel), `current_channel_index`, `delivery_status` (`pending`, `delivering`, `delivered`, `unreachable`), `last_attempt_at`, `next_attempt_at`, `failure_log` (per-channel failure context), `created_at`, `delivered_at` (nullable).
- **Invariants:**
  - Producers write atomically with their domain state change (transactional outbox pattern). If the producer's commit succeeds, the outbox entry is durable.
  - The dispatcher MUST advance current_channel_index on non-retryable failure; transient failures retry within budget on the same channel.
  - Cascade exhaustion sets delivery_status=unreachable with failure_log populated.
  - At-least-once semantics — providers without native dedup may deliver duplicates rarely; silent loss is unacceptable.
  - Producers do NOT mutate outbox entries after creation; only the dispatcher does.
- **Identifier:** `entry_id`.
- **Lifecycle:** Created by a producer's outbox write. Dispatcher drains; status advances. Delivered or unreachable entries are retained for audit; periodic cleanup retires very old delivered entries (config-driven retention).

#### Dead Letter (aggregate)

- **Root:** `DeadLetter`
- **Contains:** `dlq_id`, `origin` (`inbox` | `outbox`), `original_entry_id`, `reason`, `full_context` (payload + history), `dlq_at`.
- **Invariants:**
  - DLQ entries are immutable; remediation creates compensating events or operator intervention, never mutates the DLQ row.
  - Origin links back to the original inbox/outbox entry for full chain.
- **Identifier:** `dlq_id`.
- **Lifecycle:** Created when an inbox publication fails terminally OR an outbox cascade exhausts AND retention policy demands DLQ promotion (instead of just `unreachable`).

#### Worker State (aggregate)

- **Root:** `WorkerState`
- **Contains:** `worker_id`, `worker_kind` (`dispatcher`, `provider_listener`, etc.), `pid`, `started_at`, `last_heartbeat`, `current_lease` (which queue / range it's processing), `status`.
- **Invariants:**
  - At most one worker holds a given lease at a time (Redis-based lease coordination).
  - A worker missing heartbeats for the configured timeout is presumed dead; its lease is reclaimable.
  - Workers are stateless; restart is safe (state lives in Postgres + Redis leases).
- **Identifier:** `worker_id`.
- **Lifecycle:** Created when the daemon spawns a worker. Heartbeat updated on cadence. Removed when the worker exits cleanly OR is reclaimed after timeout.

### Domain events emitted

#### `integration.inbox.received`

- **Producer:** `integration`
- **Emitted when:** an inbound webhook (HTTP) lands, passes verification, passes allowlist, and is durably captured in the inbox.
- **Payload:** `entry_id`, `provider`, `event_name`, `payload`, `received_at`, `verified=true`, `idempotency_key`.
- **Visibility:** CLUSTER
- **Known consumers:** `agent_runtime` (for inbound messaging targeted at sessions), domain-context handlers per provider.
- **Idempotency key:** `entry_id` (which is derived from the provider's idempotency_key when available).
- **Posture:** `inbox` — durable capture first, then publish. If publish fails, the dispatcher retries; the inbox entry guarantees no loss.

#### `integration.outbox.appended`

- **Producer:** `integration`
- **Emitted when:** a new outbox entry is created (a producer wrote to its outbox table).
- **Payload:** `entry_id`, `producer_context`, `event_name`, `recipient_email`, `created_at`.
- **Visibility:** CLUSTER
- **Known consumers:** the dispatcher worker (subscribes to wake-up); operator monitoring tools.
- **Idempotency key:** `entry_id`.
- **Posture:** `commit-then-emit` (the outbox row is the durable commit; the event is a wake-up signal).

#### `integration.outbox.delivered`

- **Producer:** `integration`
- **Emitted when:** an outbox entry reaches `delivered` status (a channel accepted the delivery).
- **Payload:** `entry_id`, `delivered_at`, `delivered_via_channel`, `attempt_count`.
- **Visibility:** CLUSTER
- **Known consumers:** producers that care about delivery confirmation, audit log consumers, operator dashboards.
- **Idempotency key:** `(entry_id, delivered_at)`.
- **Posture:** `commit-then-emit`.

#### `integration.outbox.dead_lettered`

- **Producer:** `integration`
- **Emitted when:** an outbox entry's cascade exhausts AND DLQ promotion fires (configurable: some entries stay `unreachable` without DLQ if retention policy allows).
- **Payload:** `entry_id`, `dlq_id`, `reason`, `failure_log`, `dlq_at`.
- **Visibility:** CLUSTER
- **Known consumers:** operator alerting; future automated remediation.
- **Idempotency key:** `dlq_id`.
- **Posture:** `commit-then-emit`.

### Domain events consumed

#### `workflow.todo.phase_advanced`

- **Producer:** `workflow`
- **Reaction:** integration's notification dispatcher computes affected recipients per subscription rules and writes outbox entries for those who should be notified.
- **Failure handling:** subscription resolution failures are logged; integration retries the resolution; the underlying workflow event is not affected.

#### `workflow.todo.delivered`

- **Producer:** `workflow`
- **Reaction:** delivery announcement notifications — write outbox entries to interested recipients.
- **Failure handling:** same as phase_advanced.

#### `system.jobs.completed` (per the inherited job-result-notifications)

- **Producer:** any scheduled-job runner
- **Reaction:** outbox entries for the operator(s) configured to receive job notifications.
- **Failure handling:** if the recipient is unconfigured, the notification is silently dropped (degenerate cascade).

#### `agent_runtime.session.ended`

- **Producer:** `agent_runtime`
- **Reaction:** if this session was created on behalf of a remote messaging user, send a "session closed" notification back via the originating channel.
- **Failure handling:** best-effort; failure logged.

#### `config.effective.updated`

- **Producer:** `config`
- **Reaction:** re-read per-provider rate-limiting / QoS settings, channel cascade defaults, retention policies.

### Use cases

#### UC-INT-1: Inbound Telegram webhook

```
Given a Telegram bot receives a message from a user
And POSTs the update to our /webhooks/telegram endpoint
When the Telegram provider boundary module receives the request
Then it verifies the request signature (HMAC against our bot secret)
And extracts the idempotency_key (update_id from Telegram)
And parses the payload into a typed event_name (e.g., "telegram.message.text")
And checks the allowlist (provider-declared ∩ consumer-accepted) — passes
And creates an InboxEntry (verified=true, publication_status=pending)
And the dispatcher reads the entry and publishes integration.inbox.received with visibility=CLUSTER
And agent_runtime (the relevant consumer) receives the event and routes the message to the appropriate session
And the webhook responds 200 OK to Telegram
If durable capture or publication unavailable: respond with retryable error to Telegram so it retries on its side
```

#### UC-INT-2: WhatsApp verification challenge

```
Given WhatsApp performs a verification GET against /webhooks/whatsapp at registration time
When the WhatsApp provider boundary receives the challenge
Then it validates the Meta challenge value
And returns ONLY the challenge response
And NO InboxEntry is created
And NO event is published
This handshake is invisible to domain consumers
```

#### UC-INT-4: Outbound notification cascade

```
Given workflow.todo.phase_advanced fires for a phase milestone
And recipient Mo has cascade [telegram, discord, email]
When integration's notification dispatcher resolves the subscription
Then it writes an OutboxEntry (recipient=mo@example.com, cascade=[telegram, discord, email], current_channel_index=0, status=pending)
And integration.outbox.appended publishes (wake-up for the dispatcher)
And the dispatcher reads the entry and attempts Telegram delivery
On transient Telegram failure: retry within bounded budget on Telegram (current_channel_index unchanged)
On exhausted Telegram budget OR non-retryable failure: advance current_channel_index to 1 (Discord), reset attempt_count
And so on through the cascade
On Discord success: set delivery_status=delivered, delivered_via_channel=discord, emit integration.outbox.delivered
```

#### UC-INT-5: Cascade exhaustion to unreachable

```
Given an OutboxEntry's cascade [telegram, email] exhausts without success
When the dispatcher detects exhaustion on the final channel
Then it sets delivery_status=unreachable with failure_log populated (per-channel failure detail)
And does NOT promote to DLQ by default (unreachable is the observable state)
And operators can query unreachable entries via integration.list_unreachable()
```

#### UC-INT-6: Allowlist rejection on inbound

```
Given a provider sends an event the consumers have not registered to accept
When the provider boundary module checks the allowlist
Then it fails-closed: the inbound is rejected
And an InboxEntry is still created (publication_status=rejected, rejection_reason=unaccepted_event)
And NO integration.inbox.received is published
And the rejection is logged with provider, route, resolved event name (no secrets, no payload bodies)
And the external provider gets a 4xx response (or whatever the provider expects)
```

#### UC-INT-7: Worker lease and reclaim

```
Given the dispatcher worker holds a lease on outbox.cluster_a
And the worker crashes (heartbeat stops)
When the lease timeout elapses
Then the lease becomes reclaimable in Redis
And another worker (existing or freshly spawned by the daemon) picks up the lease
And resumes dispatching from the durable outbox state (no work lost)
And the previous worker's WorkerState is cleaned up
```

#### UC-INT-8: Producer transactional outbox write

```
Given workflow is about to commit a todo phase advance
When workflow opens its transaction
Then within the same transaction, workflow writes to integration.outbox via the integration crate's API
And both the todo state change and the outbox entry commit atomically
And the integration.outbox.appended event fires after commit
And the dispatcher picks up the work
And NO race exists where the todo advanced but the notification never fired
```

#### UC-INT-9: Job-completion notification (job-result-notifications inherited)

```
Given a scheduled job (e.g., nightly dependency-upgrade at 03:00) ends
When the job runner emits system.jobs.completed with (job_name, run_start, project, status, summary)
Then integration's job-notification subscriber writes an OutboxEntry for the configured operator
And the cascade attempts delivery (Telegram first per Mo's preference, email fallback)
And the operator receives the notification at ~03:05 with enough detail to act without opening a terminal
And the canary semantic holds: simulated Telegram outage → DLQ growth surfaces as observable signal
```

#### UC-INT-10: Webhook URL cutover

```
Given the v2-integration-cutover delivery happens
When external HTTP webhook routes switch from v1 to v2 endpoints
Then HTTP webhook URLs (Telegram Bot API webhook URL, GitHub webhook URL, etc.) point at v2's HTTP server
And v1 webhook receivers retire
And rollback procedure: revert the cutover PR + (if URLs were changed at the external provider) reconfigure provider URL back to v1
```

#### v1 feature inventory

Per-feature specs cataloging v1 integration behavior, authored under
`inventory-v1-integration`. v2 implementers consult these for parity.
Format: concept — path — one-line summary.

- `agent-cli-hook-reception` — `docs/project/spec/feature/integration/agent-cli-hook-reception.md` — Subprocess receiver invoked by Claude / Codex / Gemini that parses a hook payload, resolves a TeleClaude session, and enqueues the event for daemon processing.
- `hook-event-outbox` — `docs/project/spec/feature/integration/hook-event-outbox.md` — Per-session SQLite outbox between the telec-hook subprocess and the daemon, providing durable, coalesced, retry-safe transport for agent CLI hook events.
- `hook-outbox-dispatcher` — `docs/project/spec/feature/integration/hook-outbox-dispatcher.md` — Daemon worker that drains the SQLite hook outbox, classifies events critical vs bursty, enforces per-session backpressure with watermark hysteresis, and dispatches to in-process handlers or (only for AGENT_ERROR) the EventBus.
- `agent-stop-checkpoint-blocking` — `docs/project/spec/feature/integration/agent-stop-checkpoint-blocking.md` — Heuristic checkpoint engine that may block an agent_stop with an adapter-formatted instruction nudging the agent to commit, run tests, fix lint, or address uncommitted work; fail-open fallback prints CHECKPOINT_MESSAGE on internal engine failure.
- `session-state-mutation-via-outbox` — `docs/project/spec/feature/integration/session-state-mutation-via-outbox.md` — Hook outbox events that update session-row state directly (checkpoint timestamps, native binding, transcript history chain) without producing in-process EventBus events.
- `headless-session-bootstrap-from-hook` — `docs/project/spec/feature/integration/headless-session-bootstrap-from-hook.md` — When an agent_session_start hook arrives for a session the daemon has never seen, the dispatcher creates a headless session row inline from the hook payload before continuing dispatch.
- `inbound-webhook-endpoint-framework` — `docs/project/spec/feature/integration/inbound-webhook-endpoint-framework.md` — Dynamic FastAPI route registration for external inbound webhooks — provider-specific path + verification config + normalizer key, mounted at runtime from teleclaude.yml.
- `whatsapp-inbound-conversation-routing` — `docs/project/spec/feature/integration/whatsapp-inbound-conversation-routing.md` — End-to-end inbound WhatsApp pipeline (normalize → built-in contract → handler → media download → resolve-or-create session → typed command dispatch).
- `github-webhook-normalization` — `docs/project/spec/feature/integration/github-webhook-normalization.md` — GitHub webhook payload normalizer producing canonical github.<event> HookEvents; v1 built-in routing covers push/release only, ping is dropped.
- `deployment-version-fanout` — `docs/project/spec/feature/integration/deployment-version-fanout.md` — Cross-host Redis stream consumer that fans out deployment version_available events to every daemon in the cluster, with self-skip on origin to avoid double-execution; originator publishes fanout BEFORE scheduling its local execute_update.
- `eventbus-hook-bridge` — `docs/project/spec/feature/integration/eventbus-hook-bridge.md` — Subscribes to the daemon's internal EventBus, normalizes each event into a HookEvent, and runs it through the Contract matcher; bridge-emitted source/type combinations do not match any v1 production built-in contract.
- `outbound-webhook-delivery` — `docs/project/spec/feature/integration/outbound-webhook-delivery.md` — Background worker draining the webhook_outbox table, delivering HMAC-signed POSTs to subscriber URLs with exponential backoff, 4xx-permanent / 5xx-transient classification, and dead-letter at max attempts.
- `outbound-messaging-providers` — `docs/project/spec/feature/integration/outbound-messaging-providers.md` — Provider-specific send helpers for Telegram, Discord, WhatsApp Cloud API, and email (Brevo SMTP) used by notification delivery adapters and the invitation flow.
- `subscriber-driven-contract-routing` — `docs/project/spec/feature/integration/subscriber-driven-contract-routing.md` — Named exception: subscriber-published Contract / matcher model (HTTP API + YAML subscriptions, TTL, property vocabulary); v1 production exercises only three programmatic built-in contracts and no user-published ones, so the design is captured for v2 inheritance.

### Context map position

- **Customer-Supplier upstream to `agent_runtime`** — integration emits `integration.inbox.received` for inbound MESSAGING from external providers (Telegram messages, Discord messages) that target sessions. Agent CLI hooks are NOT in this relationship — agent_runtime receives those directly via `telec-hook`.
- **Customer-Supplier downstream of `workflow`** — workflow's phase-advance and delivery events drive outbox notifications.
- **Customer-Supplier downstream of `identity`** — recipient resolution uses person records + notification subscriptions stored in identity (per the inherited notification-dispatch-service requirements).
- **Customer-Supplier downstream of `config`** — provider rate limits, retention policies, cascade defaults.
- **No filesystem relationship with `agent_artifacts`** — `telec-hook` is owned by agent_runtime, not integration. agent_artifacts deploys agent_runtime's hook configs, not integration's.
- **Anti-corruption layer with v1 (during migration)** — v1 `teleclaude/hooks/` (~1600 lines), `daemon_hook_outbox.py`, `core/hook_outbox_*`, and messaging adapters (`services/{telegram,discord,whatsapp,email}.py`). The v2 ACL is broad: Python shims preserve the v1 import surface during the parallel-capable phase; v2 owns the actual logic. Disappears at `v2-integration-cutover`.

## Allowed values

- `provider`: `telegram`, `discord`, `whatsapp`, `email`, `github` (third-party only; extensible). NOT agent CLIs — those are agent_runtime's domain.
- `publication_status`: `pending`, `published`, `rejected`.
- `delivery_status`: `pending`, `delivering`, `delivered`, `unreachable`.
- `cascade channel`: `telegram`, `discord`, `whatsapp`, `email` (subset of provider list, output side).
- `worker_kind`: `dispatcher`, `provider_listener`, `reconciler`.
- `dlq origin`: `inbox`, `outbox`.

## Known caveats

- **Email is ALWAYS the final cascade fallback.** Even if the recipient didn't explicitly add email; if email credentials exist for the recipient, it's appended. The system never silently drops a notification to a recipient who has email available.
- **Admins are subscribed by default.** Above-threshold notifications go to admins without explicit subscription entries. Non-admins require explicit subscriptions.
- **Allowlist is fail-closed.** Undeclared OR unaccepted events fail at the boundary. No silent acceptance of unknown events.
- **`telec-hook` is NOT integration's binary.** It is owned by `agent_runtime`. Agent CLI hooks bypass integration entirely — they reach agent_runtime directly via IPC from `telec-hook`. Integration's only subprocess concern is binaries it owns for outbound delivery (e.g., per-provider dispatcher workers).
- **v1's two-layer plug-in routing design must carry forward.** v1 has an unused-but-instructive generic hooks service split across:

  **Layer 1 — InboundEndpointRegistry (`teleclaude/hooks/inbound.py`):**
  Dynamically mounts URL paths on the HTTP app at runtime. Each `register(path, normalizer_key, verify_config)` call adds: (a) GET handler for verification challenges (WhatsApp-style), (b) POST handler with HMAC/signature verification per the path's `verify_config`, (c) payload normalization via the path's registered normalizer producing a typed `HookEvent` (source, type, properties, payload). New external providers add a normalizer + register a path; nothing else changes.

  **Layer 2 — ContractRegistry + Matcher (`webhook_models.py` + `registry.py` + `matcher.py` + `api_routes.py`):**
  `Contract` is a subscriber's published declaration of need: `Target` (internal handler key or external URL + secret) + `source_criterion` + `type_criterion` + per-property `PropertyCriterion` (match / pattern / required). Contracts are managed via `POST /hooks/contracts`. The matcher iterates contracts and dispatches each `HookEvent` to all matching contracts' Targets.

  **The URL path is the schema.** When a webhook arrives at `/hooks/<provider>`, the path determines normalizer + verification (what arrives looks like) AND transitively, via the resulting HookEvent's source/type/properties, what consumers (Contracts) match. Adding a new external system = one normalizer + one inbound registration. Adding a new consumer = one contract POST. No core code changes for either.

  The v2-integration prepare worker MUST preserve BOTH layers (not just the Contract side). Reading order: `inbound.py` first (the plug-in inbound architecture), then `webhook_models.py` + `registry.py` + `matcher.py` + `api_routes.py` (the contract-side subscription). The two layers compose into a fully data-driven webhook routing surface.

- **NO cartridge pattern.** v1's domain cartridges are sunset for new work. Consumers subscribe via `event_bus.subscribe(...)` at daemon startup. Provider boundary modules MUST NOT import deployment or customer-relations modules.
- **Provider URL stability matters.** Webhook URLs registered with external providers (Telegram, GitHub) MUST remain stable across cutover — OR external system updates need to be coordinated (rare and expensive).
- **Worker binaries are stateless.** All state lives in Postgres (inbox, outbox, DLQ, worker_state) + Redis (leases). Worker crashes and restarts are safe.
- **No new external systems in this delivery.** Integration's scope is the supported provider set; adding a new provider requires a new boundary module + new event family + new allowlist entries — a separate delivery.
- **Inbound URL stability has its own risk profile** — see `v2-integration-cutover` input for the migration coordination.
- **Outbound URL stability** — for messaging providers, our role is the SENDER, so URL stability is the provider's concern not ours.
- **Webhook authentication is provider-specific.** Each boundary module enforces the right verification (HMAC, JWT, custom). Failure is fail-closed; no event published; provider gets an appropriate error response.
