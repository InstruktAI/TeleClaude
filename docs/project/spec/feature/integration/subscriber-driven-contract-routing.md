---
description: 'Subscriber-published Contract model — declarative source/type/property criteria attached to a handler or external URL — routed by a property-matching engine, managed via HTTP API or YAML, with TTL and sweep. Named-exception authored for v2 inheritance; v1 production exercises only the programmatic built-in subset.'
visibility: 'public'
---

# Subscriber-Driven Contract Routing — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

A subscriber-driven event-routing architecture: any module that wants
to react to an event publishes a `Contract` — a declarative match
expression combining a source criterion, a type criterion, per-property
criteria (with match, pattern, or required-presence semantics), and a
target (either an internal handler key or an external webhook URL with
HMAC secret). Contracts are persisted in the contracts store, cached
in memory by the contract registry, and matched against every dispatched
hook event by the matcher. Matched contracts are delivered via the hook
dispatcher to their handler (internal callable) or enqueued to the
webhook outbox for external delivery (see `outbound-webhook-delivery`).

Contracts can carry a TTL (an expiry timestamp); a periodic 60-second
sweep loop deactivates any contract past its expiry. The contract
management API (mounted on the integration service's internal control
plane) supports list / create / delete / query, and the YAML
`hooks.subscriptions` section can also declare contracts at startup via
the hooks config loader.

**Named exception:** the design intent (declarative subscriber routing
with API/YAML publication, TTL, property vocabulary) is documented here
even though v1 production does not exercise it — production registers
only THREE built-in contracts programmatically (`builtin-whatsapp-inbound`,
`deployment-github`, `deployment-fanout`). No production caller
publishes contracts via the management API or the YAML subscriptions
section. v2 inherits this design wholesale per the PRD's named-
exception clause.

## Canonical fields

### Use cases

#### UC-CR1: Programmatic registration of a built-in contract

```gherkin
Given the integration service wants to route inbound WhatsApp message.* events to the whatsapp-inbound handler at startup
When the service registers a contract with id="builtin-whatsapp-inbound", target handler "whatsapp_inbound", source criterion matching "whatsapp", type criterion pattern "message.*", and source="programmatic"
Then the contract is persisted with source "programmatic"
And the in-memory cache is updated with the new contract
And from now on every hook event the dispatcher receives is matched against this contract
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
When the integration service runs the hooks config loader at startup
Then the config-contract builder parses the entry into a contract with source "config"
And the contract registry persists and caches it
And an INFO "loaded config contract: my-subscriber" log is emitted
```

#### UC-CR3: Management API create with TTL (ephemeral contract)

```gherkin
Given a create request arrives with id="invite-xyz", handler target "onboarding_handler", type criterion match "session_start", ttl seconds 180
When the management endpoint runs
Then it validates exactly one of handler or URL is set on the target (else rejects as invalid)
And rejects non-positive TTL values
And computes expires-at = now + 180 seconds (ISO 8601 UTC)
And constructs a contract with source "api"
And the registry persists and caches it
And returns the created contract
```

#### UC-CR4: Management API list with optional property filter

```gherkin
Given the management endpoint receives a list request with property="session_id" and value="abc"
When the route invokes the registry's list-contracts call with that filter
Then it iterates the active, non-expired cache
And for each contract: the filter check applies when
  - the contract has a property named "session_id" whose match value equals "abc"
  OR
  - the property name is "source" or "type" and the corresponding source or type criterion matches "abc"
And returns the filtered list serialized for the API
```

#### UC-CR5: Management API delete

```gherkin
Given a delete request for a contract id arrives
When the route calls the registry's deactivate
Then the contract is marked inactive with an updated timestamp
And the cache drops the contract
And the route returns a deactivated acknowledgement (or a not-found if the contract is unknown)
```

#### UC-CR6: Match expression — exact source

```gherkin
Given a contract has a source criterion matching "whatsapp"
When the matcher runs against an event with source "whatsapp"
Then the source criterion check returns true
And other criteria are evaluated; the contract matches if all required criteria pass
Otherwise (event source "github"): the source check fails and the contract does not match
```

#### UC-CR7: Match expression — pattern

```gherkin
Given a contract has a type criterion pattern "message.*"
When the matcher runs against event type "message.image"
Then the pattern check returns true
And the contract is a candidate match
Otherwise (event type "session.started"): returns false
```

#### UC-CR8: Match expression — required presence only

```gherkin
Given a contract has properties = {"session_id": criterion(required=true)} (no match value, no pattern)
When the matcher runs with event properties["session_id"] = "sess-1"
Then required-presence semantics apply: a non-null value passes
Otherwise (session_id missing): the check fails
```

#### UC-CR9: Match expression — multi-value match list

```gherkin
Given a type criterion = match ["push", "release"]
When the matcher runs against event type "push"
Then the list-containment check returns true
```

#### UC-CR10: Property vocabulary

```gherkin
Given a list-properties request is received
When the registry's list-properties helper runs
Then it iterates active contracts
And for each criterion (source, type, per-property) it merges match values into a vocabulary map
And returns {property name: sorted values} — letting consumers introspect what filter values exist across all contracts
```

#### UC-CR11: TTL sweep deactivates expired contracts

```gherkin
Given a contract has its expires-at in the past
When the sweep loop wakes (60s cadence) and runs sweep-expired
Then it iterates the cache, identifies contracts that are expired and still active
And invokes deactivate for each — both persistence and cache update
And logs "swept N expired contracts" at info level
```

#### UC-CR12: Match excludes inactive/expired contracts at delivery time

```gherkin
Given a contract is active in cache but is expired at this instant
When the registry's match runs against an event
Then it filters by active AND not expired AND matches event
And the expired contract is excluded immediately (before the next sweep deactivates it in persistence)
And no event is delivered to an expired contract
```

#### UC-CR13: load-from-persistence on startup

```gherkin
Given the integration service starts and the contract registry is created
When the load-from-persistence step runs
Then the persistent active contracts are listed
And for each entry, the contract model is reconstructed
And on deserialization/key/type/value errors: the contract is skipped with an error log (one bad contract does not block others)
And the cache is populated atomically
And "loaded N active contracts" is logged at info level
```

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
  `deployment-fanout`) at integration service startup. No external
  module registers contracts at runtime; the management API is exposed
  but receives no production traffic; the YAML `hooks.subscriptions`
  section is empty in every shipped `teleclaude.yml`. The pattern's
  value is forward-looking — v2 will use it as the subscriber model so
  domains decouple from event routing.
- The matcher's required-presence semantics on a criterion with no
  match and no pattern translate to "the property must exist with a
  non-null value" — this required-presence-only mode is a less obvious
  behavior worth preserving in v2.
- The matcher treats the criterion as passing when it is non-required
  AND both match and pattern are unset. This means non-required
  criteria are documentation-only — they declare interest without
  filtering.
- The contract model round-trips through serialized persistence. Legacy
  keyword spellings are accepted for backwards compatibility; metadata
  fields (active, created-at, expires-at, source) are exposed via
  property accessors so the model surface stays stable.
- The contract sweep runs every 60 seconds; expired contracts are
  excluded from matching IMMEDIATELY (via the is-expired check inside
  match/list-contracts), but the persisted record stays active until
  the sweep deactivates it.
- The management API handles awaitable variants of the vocabulary
  listing for forward compatibility; v1's vocabulary listing is
  synchronous.
- The management API is mounted on the internal control-plane
  endpoint; it is not exposed publicly. External subscribers cannot
  self-register; they must go through an admin or a trusted process
  inside the integration service's host.
- v1 does NOT support contract update via partial-modification
  semantics — only create (which behaves as upsert) and delete.
- The property-filter helper supports filtering by `property=source` or
  `property=type` (mapping to the source / type criterion) AND by
  named properties. Adding a new filter dimension requires extending
  that helper.
