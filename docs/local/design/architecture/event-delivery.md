---
description: One domain-event delivery model, with source reconciliation, command ownership and runtime-local coordination kept at their existing owners.
visibility: internal
delivered_by:
  - retire-legacy-event-bus
---

# Event Delivery — Design

## Purpose

Define the relationship between domain-event publication, independent reactions,
source materialization and runtime coordination. Ownership remains with the
producing and consuming contexts under `sdlc/policy/domain-ownership`.

## Inputs/Outputs

Producers publish declared facts through the platform event producer. The
consumer runtime delivers them to interested reactions under
`local/projects/teleclaude/spec/feature/event-catalog/event-consumers`.
The event envelope states the producer's facts under
`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`.

Commands enter their owning command or operation capability. A notification
that work is requested does not substitute for that capability's acceptance,
authorization or completion contract. Runtime-local waits use the runtime's
coordination capability under
`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`.

## Invariants

- **One reaction path:** domain-event publication appends to the platform
  stream and reaction execution follows
  `local/projects/teleclaude/spec/feature/event-catalog/event-consumers`.
- **One owner per effect:** command execution, runtime coordination and event
  reactions retain their distinct completion boundaries. An awaited owner
  operation completes at that operation's boundary rather than at publication
  of a notification about it.
- **Ordered reaction, current source:** consumer progress orders that
  consumer's handling. Source materialization consumes current authoritative
  state under `local/projects/teleclaude/design/architecture/cache`; stream
  arrival order is not a database revision.
- **Producer completion:** successful publication establishes stream acceptance,
  not completion of every reaction. A source commit and a stream append are
  separate effects unless the source owner's contract supplies a durable
  handover. Publication failure stays observable and does not manufacture a
  rollback or successful delivery.
- **Compatibility at the boundary:** required earlier wire representations are
  translated at transport boundaries under
  `local/projects/teleclaude/spec/feature/reconciliation/fleet-cross-version-interop`.
  Translation retains occurrence identity and one execution path per current
  consumer. Source authority and recipient reach survive translation.
- **Preserved exposure:** a domain notification retains its source's payload
  reach, notification visibility, procedure-activation meaning and retention
  contract. Moving a control signal into an event does not grant a new reader
  access to private activity, message bodies or error details.

## Primary flows

### Domain reactions

The source owner commits its change and publishes the declared fact through
its emission contract. Each interested reaction consumes through the existing
platform consumer runtime. Its source selection, retry and duplicate handling
follow the event-consumer contract; its effects follow the consuming owner.
Session state, adapter reactions, operation outcomes, activity, voice state,
project changes and error reporting use this same relationship when they are
domain notifications.

Existing declarations represent the same fact wherever it is produced;
compatibility carriers do not create a second lifecycle occurrence. Earlier
wire handling is confined to an interoperability boundary with an explicit
fleet-capability retirement condition. Current consumers execute through the
platform path throughout that coexistence.

### Runtime and command coordination

Launch readiness and awaited hook processing follow the runtime coordination
contract in `local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`.
Command intents invoke the established command or operation owner. Local
coordination does not acquire a second event catalog, general subscriber API
or notification delivery policy.

A command continuation that needs later notification processing executes under
the command or operation owner's lifecycle; it does not occupy the ordered
reaction whose progress that continuation needs. Accepted work retains its
existing receipt and completion contract.

### Startup handover

Consumer progress is established before the source activity it must observe.
Handler execution that calls the daemon's request surface begins after that
surface is bound. Source seeding and live delivery meet at an explicit coverage
handover under
`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`.

### Cache replication and UI delivery

Peer cache replication and bootstrap retain their source and transport contract
under `local/projects/teleclaude/design/architecture/cache`. Viewer eligibility
and connection delivery remain with
`local/projects/teleclaude/design/architecture/api-server`. Domain-event
consumer order supplies neither a peer snapshot watermark nor a stronger
ordering guarantee for these separate transports.

## Failure modes

- Error-reporting failure follows its consumer's bounded failure handling and
  remains visible in structured logs; it does not create an unbounded chain of
  reports about the reporting failure.
- A publication failure after a source commit leaves reconciliation with the
  source owner. A logged exception is not evidence that a reaction completed.
- A newly established reader position can omit earlier events. Startup
  readiness includes the source-snapshot handover, not just task scheduling.
- Runtime shutdown or failed startup settles local waiters at the runtime
  boundary. Pending provider metadata cannot determine session finality.
- Earlier peers retain their declared interoperability limits. Adapting their
  envelopes does not establish source ordering absent from their records.

## See Also

- docs/local/adr/0116-each-reaction-to-a-platform-event-is-an-independent-consumer.md
- docs/local/design/architecture/cache.md
- docs/local/design/architecture/api-server.md
