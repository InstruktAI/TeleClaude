# Service Publication — Input

## Context

TeleClaude nodes can build and host services — APIs, digital products, processing
pipelines, anything. The mesh needs a way for nodes to publish what they offer and
for other nodes to discover and consume those services. No marketplace. No registry
beyond the mesh itself. Services exist because nodes advertise them and peers remember.

## A Service Is Just an Event

A service publication is a `service.published` event using the standard envelope.
The affordances describe consumption capabilities. The payload describes the service.
No separate service infrastructure — services use the same event system as everything
else.

## Local Contracts

The truth about a service lives next to its code — a local contract file (e.g.,
`contract.yaml`) describing capabilities, endpoints, pricing, consumption shape.
This is the internal truth. The AI reads this when it needs to know what the service
does.

Publication is one command: `telec mesh publish`. The AI reads the local contract,
wraps it in the event envelope, and pushes it to the mesh. Peers discover it through
gossip. Each receiving node evaluates locally — "do I care about this?" — and indexes
or ignores.

## AI-Native Authoring

The AI is the universal adapter. A human builds a service in any language, any
framework. Their AI reads the code, understands the capability, and writes the
contract in TeleClaude's schema. The user never reads schema documentation. The
documentation is FOR the AI. The AI is the interface.

When a user says "publish this," the AI:

1. Analyzes the service (endpoints, capabilities, behavior)
2. Writes the contract in TeleClaude's format
3. Stores it locally alongside the code
4. Calls `telec mesh publish`
5. The mesh carries the `service.published` event

## Transactional Capabilities

Services can include pricing in their affordances:

- `model`: per-request, subscription, free
- `rate`: credits per request (or zero)
- Consumption is metered locally by the service provider
- Settlement is bilateral between two nodes — no central clearinghouse
- If trust breaks down, you stop consuming. Market discipline, not protocol enforcement.

The transactional model is intentionally simple. No blockchain. No tokens. Just a
ledger between peers who trust each other enough to transact. Credits or direct
settlement — details to be determined as the mesh matures.

## Service Lifecycle

- `service.published` — node advertises a new service
- `service.updated` — capabilities, pricing, or endpoints changed
- `service.deprecated` — service is being phased out
- `service.removed` — service is gone

Each lifecycle event propagates through gossip. Peers that indexed the service update
their local index. A service nobody cares about naturally disappears — nobody propagates
its descriptors, nobody subscribes.

## Discovery

No service catalog server. The mesh IS the catalog. Discovery happens through gossip:
service descriptors propagate, nodes index locally, AIs interpret and recommend.

A node's AI can answer "what services are available for text analysis?" by searching
its local index of received service descriptors. If the index is thin (new node), it
asks peers for services matching its interest. Gossip fills the gap.

## Dependencies

- event-envelope-schema (service descriptors use the standard envelope)
- mesh-architecture (transport for service events)
- mesh-trust-model (trust evaluation of service providers)
- event-platform (internal processing of service events)
