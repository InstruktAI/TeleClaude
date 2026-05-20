---
id: 'project/spec/feature/integration/subscriber-driven-contract-routing'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Subscriber-published Contract model — declarative source/type/property criteria attached to a handler or external URL — routed by a property-matching engine, managed via HTTP API or YAML, with TTL and sweep. Named-exception authored for v2 inheritance; v1 production exercises only the programmatic built-in subset.'
---

# Subscriber-Driven Contract Routing — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

A subscriber-driven event-routing architecture: any module that wants to
react to an event publishes a `Contract` — a declarative match expression
combining `source_criterion`, `type_criterion`, per-property
`PropertyCriterion` instances (with `match`, `pattern`, or
required-presence semantics), and a `Target` (either an internal handler
key or an external webhook URL with HMAC secret). Contracts are stored in
the SQLite `webhook_contracts` table, cached in memory by
`ContractRegistry`, and matched against every dispatched HookEvent by
`match_event`. Matched contracts are delivered via the `HookDispatcher`
to their handler (internal callable) or enqueued to `webhook_outbox` for
external POST (see `outbound-webhook-delivery`).

Contracts can carry a TTL (`expires_at`); a periodic 60-second sweep loop
(`_contract_sweep_loop`) calls `sweep_expired()` which deactivates any
contract past its expiry. The HTTP API at `/hooks/contracts` (mounted on
the daemon's Unix socket) supports list / create / delete / query, and
the YAML `hooks.subscriptions` section can also declare contracts at
startup via `load_hooks_config`.

**Named exception:** the design intent (declarative subscriber routing
with HTTP/YAML publication, TTL, property vocabulary) is documented here
even though v1 production does not exercise it — production registers
only THREE built-in contracts programmatically (`builtin-whatsapp-inbound`,
`deployment-github`, `deployment-fanout`). No production caller publishes
contracts via the HTTP API or the YAML subscriptions section. v2 inherits
this design wholesale per the PRD's named-exception clause.

## Canonical fields

### Use cases

#### UC-CR1: Programmatic registration of a built-in contract

```gherkin
Given daemon startup wants to route inbound WhatsApp message.* events to handle_whatsapp_event
When the daemon calls await contract_registry.register(Contract(
    id="builtin-whatsapp-inbound",
    target=Target(handler="whatsapp_inbound"),
    source_criterion=PropertyCriterion(match="whatsapp"),
    type_criterion=PropertyCriterion(pattern="message.*"),
    source="programmatic"))
Then upsert_webhook_contract persists the contract_json with source="programmatic"
And the in-memory cache is updated with the new contract
And from now on every HookEvent the dispatcher receives is matched against this contract
```

#### UC-CR2: YAML-driven contract registration

```gherkin
Given teleclaude.yml contains:
    hooks:
      subscriptions:
        - id: my-subscriber
          contract:
            source:
              match: github
            type:
              match: [push, release]
          target:
            handler: deployment_update
When daemon startup runs load_hooks_config
Then _build_config_contract parses the entry into a Contract with source="config"
And contract_registry.register persists and caches it
And an INFO "Loaded config contract: my-subscriber" log is emitted
```

#### UC-CR3: HTTP API create with TTL (ephemeral contract)

```gherkin
Given a POST to /hooks/contracts with body
    {id: "invite-xyz", target: {handler: "onboarding_handler"},
     type_criterion: {match: "session_start"}, ttl_seconds: 180}
When the API route runs
Then it validates exactly one of target.handler or target.url is set (else 422)
And rejects ttl_seconds <= 0 (422)
And computes expires_at = now + 180 seconds (ISO 8601 UTC)
And constructs a Contract with source="api"
And registry.register persists + caches
And returns 201 with the serialized contract
```

#### UC-CR4: HTTP API list with optional property filter

```gherkin
Given the API receives GET /hooks/contracts?property=session_id&value=abc
When the route invokes registry.list_contracts("session_id", "abc")
Then it iterates the active, non-expired cache
And for each contract: _contract_matches_property_filter checks
  - the contract has a property named "session_id" whose match value equals "abc"
  OR
  - the property_name is "source" or "type" and the corresponding source_criterion/type_criterion matches "abc"
And returns the filtered list serialized via _contract_to_response
```

#### UC-CR5: HTTP API delete

```gherkin
Given a DELETE /hooks/contracts/<id> arrives
When the route calls registry.deactivate(contract_id)
Then deactivate_webhook_contract updates the row's active=0 and updated_at
And the cache pops the contract
And the route returns {deactivated: <id>} (or 404 if not found)
```

#### UC-CR6: Match expression — exact source

```gherkin
Given a Contract has source_criterion = PropertyCriterion(match="whatsapp")
When match_event(event, contract) runs against event.source = "whatsapp"
Then match_criterion(event.source, criterion) returns True
And other criteria are evaluated; the contract matches if all required criteria pass
Otherwise (event.source = "github"): the source check fails and the contract does not match
```

#### UC-CR7: Match expression — pattern (fnmatch)

```gherkin
Given a Contract has type_criterion = PropertyCriterion(pattern="message.*")
When match_event runs against event.type = "message.image"
Then match_criterion evaluates fnmatch.fnmatch("message.image", "message.*") = True
And the contract is a candidate match
Otherwise (event.type = "session.started"): returns False
```

#### UC-CR8: Match expression — required presence only

```gherkin
Given a Contract has properties = {"session_id": PropertyCriterion(required=True)} (no match, no pattern)
When match_criterion runs with event.properties["session_id"] = "sess-1"
Then required-presence semantics applies: value is not None → True
Otherwise (session_id missing): returns False
```

#### UC-CR9: Match expression — multi-value match list

```gherkin
Given type_criterion = PropertyCriterion(match=["push", "release"])
When match_criterion runs against event.type = "push"
Then _matches_exact_value(value, expected) checks list containment and returns True
```

#### UC-CR10: Property vocabulary

```gherkin
Given a GET /hooks/properties is received
When registry.list_properties runs
Then it iterates active contracts
And for each criterion (source, type, per-property) it merges match values into a vocab dict
And returns {property_name: sorted(values)} — letting consumers introspect what filter values exist across all contracts
```

#### UC-CR11: TTL sweep deactivates expired contracts

```gherkin
Given a contract has expires_at set to a time in the past
When _contract_sweep_loop wakes (60s cadence) and calls sweep_expired
Then it iterates the cache, identifies contract.is_expired==True && contract.active==True
And invokes deactivate(contract.id) for each — DB + cache update
And logs "Swept N expired contracts" at info level
```

#### UC-CR12: Match excludes inactive/expired contracts at delivery time

```gherkin
Given a contract is active in cache but is_expired=True at this instant
When ContractRegistry.match(event) runs
Then it filters by `c.active and not c.is_expired and match_event(event, c)`
And the expired contract is excluded immediately (before the next sweep deactivates it in DB)
And no event is delivered to an expired contract
```

#### UC-CR13: load_from_db on startup

```gherkin
Given the daemon starts and ContractRegistry is created
When load_from_db is awaited
Then db.list_webhook_contracts(active_only=True) returns all persistent active rows
And for each row, Contract.from_json reconstructs the model
And on JSON/key/type/value errors: the contract is skipped with a logger.error (one bad contract does not block others)
And the cache is populated atomically
And "Loaded N active contracts from DB" is logged at info level
```

### Implementation pointers (v1)

- `teleclaude/hooks/webhook_models.py` —
  `HookEvent` (L12),
  `PropertyCriterion` (L62),
  `Target` (L71),
  `ContractMetadata` (L80),
  `Contract` (L90, with custom `__init__` signature accepting legacy
  `contract_id`/`id` kwargs and metadata hoisting).
- `teleclaude/hooks/registry.py` —
  `ContractRegistry` (L49),
  `_criterion_matches_property_value` (L16),
  `_contract_matches_property_filter` (L25),
  `_add_match_values` (L40).
- `teleclaude/hooks/matcher.py` —
  `match_event` (L46),
  `match_criterion` (L14),
  `_matches_exact_value` (L36).
- `teleclaude/hooks/dispatcher.py` — `HookDispatcher` (L22), matched-
  Contract delivery for both handler and URL targets.
- `teleclaude/hooks/handlers.py` — `HandlerRegistry` (internal handler
  registry for handler-targeted contracts).
- `teleclaude/hooks/api_routes.py` — FastAPI router (router L18):
  `list_contracts` (L81), `list_properties` (L92),
  `create_contract` (L102), `deactivate_contract` (L143),
  `_contract_to_response` (L65), `set_contract_registry` (L22).
  Mounted on the daemon's API server (Unix socket) under `/hooks`.
- `teleclaude/hooks/config.py` —
  `load_hooks_config` (L85),
  `_build_config_contract` (L51),
  `_parse_contract_criteria` (L27),
  `parse_criterion` (L18).
- `teleclaude/core/db/_webhooks.py` — `upsert_webhook_contract`,
  `deactivate_webhook_contract`, `list_webhook_contracts`.
- `teleclaude/daemon_event_platform.py` — programmatic registration of
  three built-in contracts inside `_init_webhook_service` (L464):
  `builtin-whatsapp-inbound` (~L482), `deployment-github` (~L496),
  `deployment-fanout` (~L506); `_contract_sweep_loop` (L583, 60s
  cadence).

### Cross-context references

- Matched against every event published by `eventbus-hook-bridge`,
  inbound webhooks via `inbound-webhook-endpoint-framework`, and the
  deployment fanout consumer (`deployment-version-fanout`).
- Handler-targeted contracts deliver to internal handlers, including
  `whatsapp-inbound-conversation-routing` and the deployment handler.
- URL-targeted contracts feed `outbound-webhook-delivery`.
- Aligns with the v2 domain spec's "two-layer plug-in routing design"
  caveat under `docs/project/spec/domain/integration.md`. v2 must
  preserve BOTH layers (inbound framework AND contract subscription)
  per the PRD's named exception.

## Known caveats

- **Design intent captured for v2 inheritance; not exercised in v1
  production.** The named exception. Production registers only three
  built-in contracts (`builtin-whatsapp-inbound`, `deployment-github`,
  `deployment-fanout`) at daemon startup. No external module
  registers contracts at runtime; the HTTP API at `/hooks/contracts`
  is exposed but receives no production traffic; the YAML
  `hooks.subscriptions` section is empty in every shipped
  `teleclaude.yml`. The pattern's value is forward-looking — v2 will
  use it as the subscriber model so domains decouple from event
  routing.
- The matcher's `required=True` semantics on a criterion with
  `match=None` and `pattern=None` translate to "the property must
  exist with a non-None value" — this required-presence-only mode is
  a less obvious behavior worth preserving in v2.
- `match_criterion` treats the criterion as `True` when
  `criterion.required is False` AND match/pattern are both unset (the
  function defaults `result = True` outside the required branch).
  This means non-required criteria are documentation-only — they
  declare interest without filtering.
- `Contract.from_json` and `Contract.to_json` are designed to round-
  trip through SQLite. The model uses a private `_metadata` field
  with property accessors (`active`, `created_at`, `expires_at`,
  `source`) so the dataclass remains immutable-ish even though
  `__init__` accepts legacy keyword spellings.
- The contract sweep runs every 60 seconds; expired contracts are
  excluded from matching IMMEDIATELY (via `is_expired` check inside
  `match`/`list_contracts`), but the row stays active in SQLite until
  the sweep deactivates it.
- The API route handles `inspect.isawaitable(vocab)` for the
  `list_properties` call — defensive coding for future async
  variants; v1's `list_properties` is sync.
- The HTTP API is mounted on the internal Unix socket
  (`/tmp/teleclaude-api.sock`); it is not exposed publicly. External
  subscribers cannot self-register; they must go through an admin or
  a trusted process inside the daemon's host.
- v1 does NOT support contract update via PUT/PATCH — only POST
  (which behaves as upsert via `upsert_webhook_contract`) and DELETE.
- The `_contract_matches_property_filter` function supports filtering
  by `property=source` or `property=type` (mapping to the source /
  type criterion) AND by named properties. Adding a new
  filter dimension requires extending that helper.
