# Implementation Plan: Webhook Service

## Objective

Implement the subscriber-first, property-based event routing service. The system is built bottom-up: data models first, then matching engine, then registration paths, then bridging and delivery.

## Task 1: Event envelope and contract models [x]

**Files:** `teleclaude/hooks/webhook_models.py` (new)

- `HookEvent` dataclass: `source`, `type`, `timestamp`, `properties: dict`, `payload: dict`.
- `PropertyCriterion` dataclass: `match` (str | list | None), `pattern` (str | None), `required` (bool).
- `Contract` dataclass: `id`, `source_criterion` (PropertyCriterion), `type_criterion` (PropertyCriterion), `properties` (dict[str, PropertyCriterion]), `target` (Target), `active`, `created_at`, `source`.
- `Target` dataclass: `handler` (str | None), `url` (str | None), `secret` (str | None).
- JSON serialization helpers for DB storage.

**Verification:** Unit test — create, serialize, deserialize models.

## Task 2: Property-based matching engine [x]

**File:** `teleclaude/hooks/matcher.py` (new)

- `match_criterion(value, criterion: PropertyCriterion) -> bool`:
  - Exact match: `criterion.match == value`.
  - Multi-value: `value in criterion.match` (when list).
  - Wildcard pattern: `criterion.pattern` with dot-segment matching (`session.*` matches `session.started`).
  - Required presence: `criterion.required and criterion.match is None and criterion.pattern is None` — value must exist.
  - Optional: `not criterion.required` — always passes.
- `match_event(event: HookEvent, contract: Contract) -> bool`:
  - Check `source` against `contract.source_criterion` (if set).
  - Check `type` against `contract.type_criterion` (if set).
  - Check each property criterion in `contract.properties` against `event.properties`.
  - All required criteria must pass.

**Verification:** Unit tests for every match mode: exact, multi-value, wildcard, required, optional. Edge cases: missing property, empty properties, no criteria (match-all).

## Task 3: Contract registry (DB + Python API) [x]

**Files:**

- `teleclaude/core/db_models.py` — add `WebhookContract` SQLModel.
- `teleclaude/core/schema.sql` — add `webhook_contracts` table.
- `teleclaude/core/db.py` — add CRUD methods.
- `teleclaude/hooks/registry.py` (new) — `ContractRegistry` class.

DB schema:

```sql
CREATE TABLE IF NOT EXISTS webhook_contracts (
    id TEXT PRIMARY KEY,
    contract_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'api',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_webhook_contracts_active ON webhook_contracts(active);
```

`ContractRegistry`:

- `register(contract: Contract) -> None` — upsert into DB + in-memory cache.
- `deactivate(contract_id: str) -> None` — set active=0, remove from cache.
- `match(event: HookEvent) -> list[Contract]` — filter cached active contracts using matcher.
- `list_contracts(property_name=None, property_value=None) -> list[Contract]` — query with optional filter.
- `list_properties() -> dict[str, set[str]]` — union of all property names and their declared match values.
- In-memory contract cache refreshed from DB on startup and on write operations.

**Verification:** Unit tests — register, deactivate, match, list, property vocabulary.

## Task 4: Webhook outbox table and DB methods [x]

**Files:**

- `teleclaude/core/db_models.py` — add `WebhookOutbox` SQLModel.
- `teleclaude/core/schema.sql` — add `webhook_outbox` table.
- `teleclaude/core/db.py` — add outbox CRUD methods.

DB schema:

```sql
CREATE TABLE IF NOT EXISTS webhook_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id TEXT NOT NULL,
    event_json TEXT NOT NULL,
    target_url TEXT NOT NULL,
    target_secret TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    locked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_webhook_outbox_status ON webhook_outbox(status);
CREATE INDEX IF NOT EXISTS idx_webhook_outbox_next_attempt ON webhook_outbox(next_attempt_at);
```

DB methods (follow `hook_outbox` pattern):

- `enqueue_webhook(contract_id, event_json, target_url, target_secret)`.
- `fetch_webhook_batch(limit, now_iso) -> list`.
- `claim_webhook(row_id, now_iso, lock_cutoff_iso) -> bool`.
- `mark_webhook_delivered(row_id)`.
- `mark_webhook_failed(row_id, error, attempt_count, next_attempt_at)`.

**Verification:** Unit tests for all CRUD operations.

## Task 5: Outbound delivery worker [x]

**File:** `teleclaude/hooks/delivery.py` (new)

- `WebhookDeliveryWorker`:
  - Background async loop (registered in daemon startup).
  - Fetches pending `webhook_outbox` batch.
  - Claims and delivers each row via HTTP POST.
  - Request body: JSON-encoded `HookEvent`.
  - Headers: `Content-Type: application/json`, `X-Hook-Signature: sha256={hmac}`.
  - HMAC-SHA256 computed over request body using `target_secret`.
  - Retry with exponential backoff (1s, 2s, 4s, 8s, 16s, 32s, 60s cap).
  - 4xx → permanent failure (no retry). 5xx/timeout → transient (retry).
  - Per-row failure isolation.
- Uses `httpx.AsyncClient` for HTTP delivery.

**Verification:** Unit test with mock HTTP server — successful delivery, retry on 5xx, permanent fail on 4xx, HMAC signature verification.

## Task 6: Contract registry REST API [x]

**File:** `teleclaude/hooks/api_routes.py` (new)

- `APIRouter(prefix="/hooks", tags=["hooks"])`.
- `GET /hooks/contracts` — list active contracts, optional `property` and `value` query params.
- `GET /hooks/properties` — union of all declared properties.
- `POST /hooks/contracts` — create contract from JSON body.
- `DELETE /hooks/contracts/{contract_id}` — deactivate.
- Register router in `api_server.py` via `app.include_router()`.

**Verification:** Unit test — API round-trip: create, list, filter, delete.

## Task 7: Internal handler registry [x]

**File:** `teleclaude/hooks/handlers.py` (new)

- `HandlerRegistry`:
  - `register(key: str, handler: Callable[[HookEvent], Awaitable[None]])`.
  - `get(key: str) -> Callable | None`.
- Used by adapters to register internal handlers at startup.
- Delivery to internal handlers is direct async call (no outbox).

**Verification:** Unit test — register handler, deliver event, handler called.

## Task 8: Event dispatcher (routing core) [x]

**File:** `teleclaude/hooks/dispatcher.py` (new)

- `HookDispatcher`:
  - `dispatch(event: HookEvent) -> None`:
    - Match event against all active contracts via `ContractRegistry.match()`.
    - For each matching contract:
      - If `target.handler`: call via `HandlerRegistry.get()` — direct async.
      - If `target.url`: enqueue in `webhook_outbox` — async delivery via worker.
  - Non-blocking — dispatch runs in background task.

**Verification:** Unit test — event dispatched to internal handler and external outbox correctly.

## Task 9: Internal event bus bridge [x]

**File:** `teleclaude/hooks/bridge.py` (new)

- `EventBusBridge`:
  - Subscribes to all `EventType` values on the existing `event_bus`.
  - Handler maps `EventType` + `EventContext` → `HookEvent`:
    - `source`: derived from event type (e.g., `agent_event` → `"agent"`, `error` → `"system"`).
    - `type`: mapped from `EventType` + `AgentHookEventType` (e.g., `"agent_event"` with `tool_done` → `"agent.tool.completed"`).
    - `properties`: extracted from typed payloads (`session_id`, `tool_name`, `agent`, etc.).
    - `payload`: serialized `EventContext` data.
  - Calls `HookDispatcher.dispatch()` for each normalized event.
- Registered at daemon startup.

**Verification:** Unit test — internal event emitted, bridge normalizes and dispatches, matching contract receives event.

## Task 10: Inbound webhook endpoint framework [x]

**File:** `teleclaude/hooks/inbound.py` (new)

- `InboundEndpointRegistry`:
  - `register(path: str, normalizer_key: str, verify_config: dict)` — registers a FastAPI route dynamically.
  - GET handler: verification challenge support (configurable per source).
  - POST handler: verify authenticity → call normalizer → dispatch via `HookDispatcher`.
- `NormalizerRegistry`:
  - `register(key: str, normalizer: Callable[[dict], HookEvent])`.
  - `get(key: str) -> Callable | None`.
- Inbound endpoints registered from config at startup or programmatically.
- No platform-specific normalizers in this todo — that's for adapter todos.

**Verification:** Unit test — register endpoint, POST payload, normalizer called, event dispatched.

## Task 11: Config loading [x]

**Files:** `teleclaude/config/schema.py`, `teleclaude/hooks/config.py` (new)

- Add `HooksConfig` model to config schema:

  ```python
  class InboundSourceConfig(BaseModel):
      path: str
      verify_token: str | None = None
      secret: str | None = None
      normalizer: str

  class SubscriptionConfig(BaseModel):
      id: str
      contract: dict  # property criteria
      target: dict    # handler or url + secret

  class HooksConfig(BaseModel):
      inbound: dict[str, InboundSourceConfig] = {}
      subscriptions: list[SubscriptionConfig] = []
  ```

- Config loader converts `SubscriptionConfig` → `Contract` and registers at startup.
- Inbound sources registered as endpoints at startup.

**Verification:** Config parsing test with hooks section.

## Task 12: Daemon integration [x]

**File:** `teleclaude/daemon.py`

- Initialize `ContractRegistry`, `HandlerRegistry`, `NormalizerRegistry`, `HookDispatcher`, `WebhookDeliveryWorker`, `EventBusBridge` at startup.
- Load config-driven contracts and inbound endpoints.
- Start delivery worker background loop.
- Register hooks API router on the FastAPI app.
- Graceful shutdown: stop delivery worker, flush pending.

**Verification:** Daemon starts cleanly with hooks config, delivery worker running.

## Task 13: Tests [x]

**File:** `tests/unit/test_webhook_service.py` (new)

- Event envelope creation and serialization.
- All matching modes: exact, multi-value, wildcard, required, optional, match-all.
- Contract registry CRUD + matching.
- Webhook outbox CRUD.
- Delivery worker: success, retry, permanent fail, HMAC.
- Dispatcher: internal handler + external outbox routing.
- Event bus bridge: internal event normalization.
- Inbound endpoint: POST → normalize → dispatch.
- Config parsing.
- Contract filter API: by property name, by value.
- Property vocabulary endpoint.

## Files Changed

| File                                 | Change                                        |
| ------------------------------------ | --------------------------------------------- |
| `teleclaude/hooks/webhook_models.py` | New — event envelope + contract models        |
| `teleclaude/hooks/matcher.py`        | New — property-based matching engine          |
| `teleclaude/hooks/registry.py`       | New — contract registry (DB-backed + cache)   |
| `teleclaude/hooks/handlers.py`       | New — internal handler registry               |
| `teleclaude/hooks/dispatcher.py`     | New — event routing core                      |
| `teleclaude/hooks/delivery.py`       | New — outbound webhook delivery worker        |
| `teleclaude/hooks/bridge.py`         | New — internal event bus bridge               |
| `teleclaude/hooks/inbound.py`        | New — inbound webhook endpoint framework      |
| `teleclaude/hooks/config.py`         | New — config loading for hooks section        |
| `teleclaude/hooks/api_routes.py`     | New — REST API for contract registry          |
| `teleclaude/core/db_models.py`       | Add WebhookContract + WebhookOutbox models    |
| `teleclaude/core/schema.sql`         | Add webhook_contracts + webhook_outbox tables |
| `teleclaude/core/db.py`              | Add CRUD methods for contracts + outbox       |
| `teleclaude/config/schema.py`        | Add HooksConfig model                         |
| `teleclaude/daemon.py`               | Initialize hooks subsystem at startup         |
| `teleclaude/api_server.py`           | Include hooks API router                      |
| `tests/unit/test_webhook_service.py` | New tests                                     |

## Build Order

Tasks are ordered for incremental merge safety:

1. Models (Task 1) — no dependencies, pure data.
2. Matcher (Task 2) — depends on models only.
3. Registry (Task 3) — depends on models + DB.
4. Outbox (Task 4) — depends on DB only.
5. Delivery worker (Task 5) — depends on outbox.
6. Registry API (Task 6) — depends on registry.
7. Handler registry (Task 7) — standalone.
8. Dispatcher (Task 8) — integrates registry + handler + outbox.
9. Bridge (Task 9) — integrates dispatcher + event bus.
10. Inbound (Task 10) — integrates dispatcher + normalizer.
11. Config (Task 11) — integrates all registries.
12. Daemon (Task 12) — wiring.
13. Tests (Task 13) — comprehensive.

## Risks

1. **Scope** — 13 tasks is substantial. The matching engine, registry, and dispatcher are the core value; delivery worker and inbound framework are incremental. If session runs long, Tasks 1-3 + 7-8 form a minimal viable core.
2. **Performance** — O(n) contract matching per event. Acceptable for <100 contracts. If needed later, index contracts by `source` and `type` for faster lookup.
3. **httpx dependency** — used for outbound delivery. Already in the dependency tree (check `pyproject.toml`). If not, add it.
4. **Existing hooks/ directory** — `teleclaude/hooks/` already has `receiver.py`. New files coexist; naming is distinct (`webhook_models.py`, `matcher.py`, etc.).

## Cross-References

- **Outbox design**: `docs/project/design/architecture/outbox.md` — followed for webhook delivery.
- **Event bus**: `teleclaude/core/event_bus.py` — bridge subscribes here.
- **API router pattern**: `teleclaude/memory/api_routes.py` — followed for hooks API.
- **help-desk-whatsapp** — will provide WhatsApp normalizer + subscriber contract.
