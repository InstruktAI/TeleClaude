---
description: One domain-event delivery model, with source reconciliation, command
  ownership and runtime-local coordination kept at their existing owners.
visibility: internal
---

# Event Delivery — Design

## Purpose

Define the relationship between domain-event publication, independent reactions,
source materialization and runtime coordination. Ownership remains with the
producing and consuming contexts under `sdlc/policy/domain-ownership`.

## Inputs/Outputs

Producers publish declared facts through the event publication capability for
their source stream. The consumer runtime delivers them to interested reactions under
`local/projects/teleclaude/spec/feature/event-catalog/event-consumers`.
The event envelope states the producer's facts under
`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`.

Commands enter their owning command or operation capability. A notification
that work is requested does not substitute for that capability's acceptance,
authorization or completion contract. Runtime-local waits use the runtime's
coordination capability under
`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`.

## Invariants

- **One reaction path:** domain-event publication appends to its source stream
  and reaction execution follows
  `local/projects/teleclaude/spec/feature/event-catalog/event-consumers`.
  Source-owned local cache reconciliation is a separate owner capability under
  `local/projects/teleclaude/design/architecture/cache`; publication does not
  invoke a general in-process subscriber path.
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
- **Each scope its own Redis:** every event type states its scope, local by
  default and cluster when a consumer on another computer acts on it.
  Publication appends an event to the Redis of its scope: the computer's own
  local Redis, or the shared cluster Redis. A consumer reads from the Redis of
  every scope its event types belong to, so an event produced and consumed on
  one computer never crosses the network.
- **Compatibility at the boundary:** required earlier wire representations are
  translated at transport boundaries under
  `local/projects/teleclaude/spec/feature/reconciliation/fleet-cross-version-interop`.
  The earlier internal wire and its named capability gate are defined below.
  Translation retains occurrence identity, source authority and recipient reach.
- **Preserved exposure:** a domain notification retains its source's payload
  reach, notification visibility, procedure-activation meaning and retention
  contract. Moving a control signal into an event does not grant a new reader
  access to private activity, message bodies or error details.

## Primary flows

### Domain reactions

The source owner commits its change and publishes the declared fact through
its emission contract. Each interested reaction consumes through the existing
independent-consumer runtime. Its source selection, retry and duplicate handling
follow the event-consumer contract; its effects follow the consuming owner.
Adapter reactions, operation outcomes, activity, voice state,
project changes and error reporting use this same relationship when they are
domain notifications.

Existing declarations represent the same fact wherever it is produced;
compatibility carriers do not create a second lifecycle occurrence. Current
consumers execute through their bound consumer path throughout wire coexistence.

### Local session projection

The daemon's session-source change boundary attempts current-source cache
reconciliation before publishing its domain notification, under
`local/projects/teleclaude/design/architecture/cache`. The live materializer
consumer recovers from current source state before retiring its historical
delivery position. Source projection and notification consumption remain
separate completion boundaries under `sdlc/policy/domain-ownership`.

### Source-stream exposure

Public platform facts retain the platform stream and its existing consumers.
Internal runtime notifications retain the stream owned by
`INTERNAL_EVENT_STREAM`, with typed decoding and consumer-owned live or retained delivery
on the same delivery runtime. This stream boundary preserves the existing
notification, procedure-activation, maintenance and correlation inputs under
`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`.

The two sources share delivery mechanics, not audiences. Internal notifications
do not enter public automation through translation. Native facts retain their
truthful source, subject and origin; earlier records retain the limits of the
facts they carried. Source-stream trimming and the existing dead-letter contract
remain authoritative; the transport creates no additional payload archive.

Runtime typing, activity, lifecycle feedback, error feedback and operation
toasts are live presentation. Session cache, adapter metadata, availability,
voice focus and terminal housekeeping recover from their owning current state
before replacing historical delivery. Legacy command carriers retain ordered
delivery until handed to their command owner; public occurrence consumers are
unchanged. The delivery distinction belongs to each reaction under
`local/projects/teleclaude/spec/feature/event-catalog/event-consumers`, not to a
producer's assessment of an event's importance.

Readiness and no-composer evidence remain runtime-owned operations. Explicit
voice focus completes through its command-owned voice continuation. Local
project-cache changes use the existing cache-change capability. These operations
retain their local payload reach and completion boundaries under
`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`.

### Scopes and their Redis

The local Redis runs on each computer under the operating system's service
manager, listens only on a Unix socket that only the computer's user and the
Redis service can open, and requires its own user and password.
The cluster Redis is shared by the computers of one cluster; it also carries
the cross-computer transport of
`local/projects/teleclaude/design/architecture/redis-transport`.

Both Redis instances hold the platform stream and the stream owned by
`INTERNAL_EVENT_STREAM`; an entry is on exactly one of them. The cluster types
are those a consumer on another computer acts on: relayed ingress events, the
revision and release facts installation reaction admits, the session status,
agent activity and error notifications that views of another computer's
sessions show, and the earlier internal compatibility ingress. Every other type
is local. The set of cluster types has one owner in code, and a new
cross-computer consumer changes it in the same change.

A consumer whose interest names only local types reads the local Redis; one
naming only cluster types reads the cluster Redis; one taking any type reads
both and keeps separate progress on each. Own-computer filtering applies to
what each Redis delivers.

### Earlier internal wire interoperability

The compatibility surface is the earlier `InternalEventEnvelope` representation
on the stream owned by `INTERNAL_EVENT_STREAM`. Current consumers decode earlier
entries directly through the transport codec. A source append carries canonical
attributes beside any earlier representation required by peers; the general emitter's
local dispatch and subscriber registry are not compatibility surfaces.

The feature-ID registry owns the domain-event-delivery capability named
`DOMAIN_EVENT_DELIVERY_FEATURE_ID`, marked `MUST_NEGOTIATE`. A node advertises
this capability when it supports the migrated domain notifications through
platform consumers and preserves occurrence identity across the canonical and
earlier wire representations. Publishing a pending contract does not advertise
implementation support.

Earlier wire handling remains available while the live fleet requires it.
Its withdrawal uses the existing fleet capability map's contraction answer for
`DOMAIN_EVENT_DELIVERY_FEATURE_ID`: every live node, including the slowest
channel, advertises that capability. A missing map, an empty live set or a live
node lacking the advertisement leaves withdrawal closed. Release numbers alone
do not open it. This applies the retirement contract in
`local/projects/teleclaude/spec/feature/reconciliation/fleet-cross-version-interop`.

The adapter carries the same occurrence identity across representations and
does not append a translated copy to the platform stream. A current consumer
has one effective reaction path for that occurrence. Wire compatibility does
not preserve the earlier general-purpose event execution machinery, and the
separate peer cache replication protocol retains its existing contract.
Withdrawal retires the earlier representation, while the internal source stream
retains its exposure boundary.
Retained earlier entries remain decodable while any consumer still owes their
handling; fleet capability alone does not discard pending work.

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
- docs/local/adr/0139-each-event-scope-has-its-own-redis.md — why each event scope has its own Redis.
- docs/local/design/architecture/cache.md
- docs/local/design/architecture/api-server.md
