---
description: 'Contract-based pub/sub webhook service for event routing, inbound webhook reception, and durable external delivery.'
id: 'project/design/architecture/hook-service'
scope: 'project'
type: 'design'
---

# Hook Service — Design

## Required reads

- @docs/project/design/architecture/outbox.md
- @docs/project/design/architecture/daemon.md
- @docs/project/spec/event-types.md

## Purpose

Provide a contract-based pub/sub system that:

1. Routes internal daemon events (session lifecycle, agent activity, errors) to
   registered subscribers via declarative contracts.
2. Receives inbound webhooks from external platforms (GitHub, WhatsApp, etc.),
   normalizes them into a canonical event format, and dispatches them through
   the same contract-matching pipeline.
3. Delivers matched events to internal async handlers or external URLs with
   durable outbox semantics (retry, backoff, dead-lettering).

The hook service is a **monolith subsystem** — it lives inside the TeleClaude
daemon, not as a separate service. It shares the daemon's DB, event bus, and
FastAPI app.

## Two event systems in TeleClaude

TeleClaude has two distinct event persistence systems. Understanding the
boundary prevents confusion:

| System                         | Table(s)                              | Purpose                                      | Producer                                        | Consumer                                          |
| ------------------------------ | ------------------------------------- | -------------------------------------------- | ----------------------------------------------- | ------------------------------------------------- |
| **Hook outbox** (agent CLI)    | `hook_outbox`                         | Durable ingest of raw agent CLI hook events  | Agent hook receiver (`bin/hook-receiver`)       | Daemon outbox worker (see @outbox.md)             |
| **Webhook service** (this doc) | `webhook_contracts`, `webhook_outbox` | Contract-based pub/sub for normalized events | EventBusBridge, inbound endpoints, programmatic | HookDispatcher → handlers / WebhookDeliveryWorker |

The hook outbox is the **ingestion layer** — it captures raw agent CLI events
and persists them until the daemon processes them. The webhook service is the
**routing layer** — it takes normalized events (from the event bus or inbound
endpoints) and fans them out to subscribers via contracts.

The bridge between them: when the daemon processes a `hook_outbox` row, it emits
domain events onto the internal event bus. The `EventBusBridge` picks those up,
normalizes them to `HookEvent`, and dispatches them through the webhook service
pipeline.

## Inputs/Outputs

**Inputs:**

- Internal domain events from the event bus (SESSION_STARTED, SESSION_CLOSED,
  SESSION_UPDATED, AGENT_EVENT, AGENT_ACTIVITY, ERROR)
- Inbound HTTP POST payloads from external platforms (via dynamic FastAPI routes)
- Config-driven contracts from `teleclaude.yml` `hooks` section
- API-created contracts via REST endpoints (`POST /hooks/contracts`)
- Programmatic contracts registered by daemon subsystems

**Outputs:**

- Internal handler invocations (async callables called in-process)
- External webhook deliveries via the `webhook_outbox` table (durable, retried)
- Contract metadata queryable via REST API (`GET /hooks/contracts`,
  `GET /hooks/properties`)

## Invariants

- **Contract-first routing.** Events are only delivered to targets that have a
  matching active contract. No contract = no delivery. This is intentional: the
  system is subscriber-first, not publisher-first.
- **Canonical event format.** All events — whether from the internal event bus or
  inbound webhooks — are normalized to `HookEvent(source, type, timestamp,
properties, payload)` before entering the dispatch pipeline.
- **Dual delivery semantics.** Internal handlers are called synchronously
  (in-process, fire-and-forget per handler). External URLs use durable outbox
  delivery with retry. A contract targets exactly one: `handler` XOR `url`.
- **At-least-once external delivery.** External webhooks are enqueued in
  `webhook_outbox` and delivered with exponential backoff. Dead-lettering after
  max attempts prevents infinite retry.
- **Contract TTL.** Contracts may have `expires_at`. A background sweep
  deactivates expired contracts every 60 seconds.
- **HMAC verification.** Inbound endpoints verify `X-Hub-Signature-256` or
  `X-Hook-Signature` when a secret is configured. Outbound deliveries sign
  payloads with `X-Hook-Signature` using the contract's target secret.

## Primary flows

### 1. Internal event → contract match → delivery

This is the most common flow. An internal daemon event reaches a subscriber.

```
EventBus                 EventBusBridge              HookDispatcher
  │                           │                           │
  ├─ emit(SESSION_STARTED) ──►│                           │
  │                           ├─ normalize to HookEvent ─►│
  │                           │   source="system"         ├─ match against
  │                           │   type="session.started"  │  ContractRegistry
  │                           │   properties={session_id}  │
  │                           │                           ├─ for each match:
  │                           │                           │   ├─ handler? → call
  │                           │                           │   └─ url? → enqueue
  │                           │                           │      in webhook_outbox
```

**EventBusBridge normalization rules:**

| Internal event    | HookEvent source | HookEvent type                | Properties                                                          |
| ----------------- | ---------------- | ----------------------------- | ------------------------------------------------------------------- |
| `SESSION_STARTED` | `system`         | `session.started`             | `session_id`                                                        |
| `SESSION_CLOSED`  | `system`         | `session.closed`              | `session_id`                                                        |
| `SESSION_UPDATED` | `system`         | `session.updated`             | `session_id`                                                        |
| `AGENT_EVENT`     | `agent`          | `agent.{event_type}`          | `session_id`, `agent_event_type`                                    |
| `AGENT_ACTIVITY`  | `agent`          | `agent.activity.{event_type}` | `session_id`, `agent_event_type`, `tool_name` (if present)          |
| `ERROR`           | `system`         | `error.{severity}`            | `session_id` (if present), `severity`, `error_source`, `error_code` |

### 2. Inbound webhook → normalize → dispatch

An external platform sends a webhook to TeleClaude.

```
External platform          InboundEndpointRegistry       NormalizerRegistry
  │                              │                             │
  ├─ POST /hooks/github ────────►│                             │
  │                              ├─ verify HMAC signature      │
  │                              ├─ parse JSON body            │
  │                              ├─ lookup normalizer ────────►│
  │                              │                             ├─ return normalizer fn
  │                              ├─ normalizer(payload) ──────►│
  │                              │  → HookEvent                │
  │                              ├─ dispatch(event) ──────────►HookDispatcher
  │                              │                             │  (same as flow 1)
  │  ◄── 200 {"status":"accepted"}                             │
```

**Inbound endpoint lifecycle:**

1. Config declares an inbound source in `teleclaude.yml`:
   ```yaml
   hooks:
     inbound:
       github:
         path: /hooks/github
         secret: ${GITHUB_WEBHOOK_SECRET}
         normalizer: github
   ```
2. `load_hooks_config` calls `InboundEndpointRegistry.register(path, normalizer_key, verify_config)`.
3. Two routes are mounted on the FastAPI app: GET (verification challenge) and POST (payload).
4. POST handler: verify signature → parse JSON → normalize → dispatch → return 200.

**Normalizer contract:** A normalizer is a `Callable[[dict], HookEvent]` registered
in the `NormalizerRegistry`. It transforms platform-specific payloads into canonical
`HookEvent` instances. Each platform flavor (GitHub, WhatsApp, etc.) provides its
own normalizer.

### 3. Outbound delivery (webhook_outbox)

When a contract targets an external URL, the dispatcher enqueues to `webhook_outbox`.

```
webhook_outbox table        WebhookDeliveryWorker         External URL
  │                              │                             │
  │  ◄── INSERT (pending) ───── HookDispatcher                │
  │                              │                             │
  │  ── poll every 2s ──────────►│                             │
  │                              ├─ claim row (locked_at)      │
  │                              ├─ sign with HMAC if secret   │
  │                              ├─ POST event_json ──────────►│
  │                              │                             │
  │                              │  ◄── HTTP response ────────┤
  │                              │                             │
  │                              ├─ <200: mark delivered       │
  │                              ├─ 4xx: mark rejected (final) │
  │                              └─ 5xx/timeout: retry+backoff │
```

**Retry schedule:**

| Attempt | Delay   |
| ------- | ------- |
| 1       | 1s      |
| 2       | 2s      |
| 3       | 4s      |
| 4       | 8s      |
| 5       | 16s     |
| 6       | 32s     |
| 7+      | 60s cap |

After 10 attempts: dead-lettered (status=`dead_letter`).

### 4. Contract lifecycle

Contracts enter the system through three paths:

| Source           | How                                                   | Persistence                                    |
| ---------------- | ----------------------------------------------------- | ---------------------------------------------- |
| **Config**       | `teleclaude.yml` `hooks.subscriptions` list           | Loaded at startup via `load_hooks_config` → DB |
| **API**          | `POST /hooks/contracts`                               | DB + in-memory cache                           |
| **Programmatic** | `contract_registry.register(contract)` in daemon code | DB + in-memory cache                           |

All contracts are persisted in the `webhook_contracts` table and cached
in-memory by `ContractRegistry`. The cache is the authoritative source for
matching; DB is the durable store that survives restarts.

**Contract structure:**

```
Contract
  ├─ id: str                    # unique identifier
  ├─ target: Target
  │   ├─ handler: str | None    # internal handler key (XOR with url)
  │   └─ url: str | None        # external webhook URL
  │   └─ secret: str | None     # HMAC signing key
  ├─ source_criterion: PropertyCriterion | None
  ├─ type_criterion: PropertyCriterion | None
  ├─ properties: dict[str, PropertyCriterion]
  ├─ active: bool
  ├─ expires_at: str | None     # TTL support
  └─ source: "config" | "api" | "programmatic"
```

**Matching:** The matcher evaluates an event against a contract's criteria using
AND logic — all criteria must pass. Each `PropertyCriterion` supports:

- **Exact match:** `match: "value"` or `match: ["val1", "val2"]`
- **Wildcard pattern:** `pattern: "session.*"` (fnmatch)
- **Presence check:** `required: true` with no match/pattern (value must not be None)
- **Documentation-only:** `required: false` (always passes)

### 5. Daemon initialization wiring

`daemon.py:_init_webhook_service()` boots the entire subsystem:

```python
# 1. Create registries
contract_registry = ContractRegistry()       # DB-backed, in-memory cache
handler_registry  = HandlerRegistry()        # key → async callable

# 2. Create dispatcher (routes events to targets)
dispatcher = HookDispatcher(contract_registry, handler_registry, db.enqueue_webhook)

# 3. Create bridge (event bus → dispatcher)
bridge = EventBusBridge(dispatcher)

# 4. Create delivery worker (webhook_outbox → HTTP)
delivery_worker = WebhookDeliveryWorker()

# 5. Load state
await contract_registry.load_from_db()       # restore contracts from DB
await load_hooks_config(hooks_cfg, contract_registry)  # add config contracts

# 6. Wire into daemon
set_contract_registry(contract_registry)     # inject into API routes
bridge.register(event_bus)                   # subscribe to event bus
# Start background tasks
asyncio.create_task(delivery_worker.run(shutdown_event))
asyncio.create_task(contract_sweep_loop())   # TTL sweep every 60s
```

## Configuration

The `hooks` section in `teleclaude.yml`:

```yaml
hooks:
  # Inbound: receive webhooks from external platforms
  inbound:
    github:
      path: /hooks/github
      secret: ${GITHUB_WEBHOOK_SECRET}
      normalizer: github
    whatsapp:
      path: /hooks/whatsapp
      verify_token: ${WHATSAPP_VERIFY_TOKEN}
      secret: ${WHATSAPP_SECRET}
      normalizer: whatsapp

  # Subscriptions: declare interest in events
  subscriptions:
    - id: notify-on-error
      contract:
        source:
          match: system
        type:
          pattern: 'error.*'
      target:
        url: https://example.com/alerts
        secret: ${ALERT_SECRET}

    - id: log-sessions
      contract:
        type:
          pattern: 'session.*'
      target:
        handler: session_logger
```

**Config schema classes:**

- `HooksConfig`: top-level container with `inbound` and `subscriptions`
- `InboundSourceConfig`: `path`, `verify_token`, `secret`, `normalizer`
- `SubscriptionConfig`: `id`, `contract` (dict), `target` (dict)

## REST API

| Method   | Path                    | Description                                                |
| -------- | ----------------------- | ---------------------------------------------------------- |
| `GET`    | `/hooks/contracts`      | List active contracts (filter by `?property=X&value=Y`)    |
| `POST`   | `/hooks/contracts`      | Create contract (supports `ttl_seconds` for auto-expiry)   |
| `DELETE` | `/hooks/contracts/{id}` | Deactivate a contract                                      |
| `GET`    | `/hooks/properties`     | Union of all property names/values across active contracts |

## Database tables

**`webhook_contracts`** — Contract persistence:

| Column          | Type    | Purpose                                 |
| --------------- | ------- | --------------------------------------- |
| `id`            | TEXT PK | Contract identifier                     |
| `contract_json` | TEXT    | Full serialized contract                |
| `active`        | INTEGER | 0/1 soft-delete flag                    |
| `source`        | TEXT    | Origin: "config", "api", "programmatic" |
| `created_at`    | TEXT    | ISO 8601                                |
| `updated_at`    | TEXT    | ISO 8601                                |

**`webhook_outbox`** — Durable external delivery queue:

| Column            | Type       | Purpose                                |
| ----------------- | ---------- | -------------------------------------- |
| `id`              | INTEGER PK | Auto-increment row ID                  |
| `contract_id`     | TEXT       | Which contract triggered delivery      |
| `event_json`      | TEXT       | Serialized HookEvent                   |
| `target_url`      | TEXT       | Delivery destination                   |
| `target_secret`   | TEXT       | HMAC signing key (nullable)            |
| `status`          | TEXT       | pending/delivered/rejected/dead_letter |
| `attempt_count`   | INTEGER    | Delivery attempts so far               |
| `next_attempt_at` | TEXT       | When to retry (ISO 8601)               |
| `last_error`      | TEXT       | Most recent failure reason             |
| `locked_at`       | TEXT       | Claim lock timestamp                   |

## Module layout

```
teleclaude/hooks/
  ├─ webhook_models.py    # HookEvent, Contract, Target, PropertyCriterion
  ├─ registry.py          # ContractRegistry (DB + cache)
  ├─ dispatcher.py        # HookDispatcher (event → contract match → deliver)
  ├─ matcher.py           # Property-based matching engine (fnmatch, exact, multi-value)
  ├─ handlers.py          # HandlerRegistry (key → async callable)
  ├─ bridge.py            # EventBusBridge (internal event bus → HookEvent → dispatch)
  ├─ delivery.py          # WebhookDeliveryWorker (outbox poller, HMAC, retry)
  ├─ inbound.py           # InboundEndpointRegistry, NormalizerRegistry
  ├─ config.py            # load_hooks_config (teleclaude.yml → contracts + endpoints)
  ├─ api_routes.py        # FastAPI router (/hooks/contracts, /hooks/properties)
  └─ adapters/
      └─ base.py          # HookAdapter protocol (agent CLI hook normalization)
```

## Failure modes

- **Bridge dispatch error.** Caught and logged. Does not crash the event bus
  subscriber. The internal event is consumed regardless — failed dispatch is
  logged, not retried at the bridge level (the event bus is fire-and-forget).
- **Internal handler exception.** Caught per-handler. Other matching contracts
  still receive the event. No retry — internal handlers are expected to be
  idempotent and fast.
- **External delivery failure (5xx/timeout).** Retried with exponential backoff
  via `webhook_outbox`. After 10 attempts, dead-lettered.
- **External delivery rejection (4xx).** Permanent failure. Marked `rejected`,
  not retried. The receiver explicitly rejected the payload.
- **Inbound normalization failure.** Returns HTTP 400 to the sending platform.
  Event is not dispatched. The platform may retry per its own policy.
- **Inbound dispatch failure.** Returns HTTP 200 to prevent platform retries
  (many platforms retry on non-2xx). Logs the error. Event is lost for this
  delivery attempt — the platform believes it was accepted.
- **Contract sweep race.** If an event matches a contract that expires mid-dispatch,
  the event is still delivered (the match happened before expiry). This is
  acceptable: TTL is approximate, not transactional.
- **Daemon restart.** Contracts reload from DB. In-flight `webhook_outbox` rows
  with `status=pending` are picked up by the new delivery worker. No events lost
  for external targets. Internal handler events that were in-flight are lost
  (they were in-process, not persisted).
