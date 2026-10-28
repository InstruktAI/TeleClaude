---
visibility: internal
description: Frozen v1 ownership anchor for external-provider and process-boundary integration behavior.
---

# Integration Domain Spec — Spec

## What it is

The v1 integration area inventories behavior crossing provider, process, and
delivery boundaries, including inbound adapters, outbound notifications, agent
hook reception, and code-integration workflow surfaces. Its feature specs and
implementation remain the current appliance contract.

## Canonical fields

- **Current behavior:** `docs/local/spec/feature/integration/`.

- **Implementation roots:** `teleclaude/adapters/`,
  `teleclaude/core/integration/`, and `teleclaude/core/inbound/`.

- **Maintenance stance:** see `local/projects/teleclaude/spec/domain/glossary`. No replacement transport design is
  authored here.

### Ownership boundary

- **Owns:** provider and process transport, inbound normalization, outbound
  delivery mechanics, and translation across external boundaries.
- **Does not own:** session-input acceptance or execution, identity policy,
  todo lifecycle, or presentation policy merely because integration carries
  the message.
- **Owns (live voice transport):** the personal Discord voice room's
  connection lifecycle, encrypted media transport across the two-process
  boundary, the explicit transmission framing that opens and closes one
  push-to-talk utterance, discarding audio from any speaker other than the
  configured person, and playback of a rendered audio artifact into the room.
  Utterance closure is provider protocol semantics and resolves here: the
  sender-emitted stop sequence is the push-to-talk release and the only close,
  and an absent or unorderable sequence produces no handoff.
- **Owns (voice connection ownership):** which computer holds the connection
  for a bot identity in a guild. A personal voice channel has no forum
  ancestry, so ownership is not derived from a project category; it follows
  the mesh master — the one computer that already provisions this bot's
  shared Discord structure — and a peer that receives the same provider event
  performs no voice side effect.
- **Does not own (voice):** which session the person is listening to, what a
  session's spoken reply says, how audio is rendered, or whether a
  transcription becomes agent input. Integration hands a closed utterance to
  the established voice-input contract and plays what it is given.
- **Published contracts:** normalized inbound commands and events, outbound
  delivery requests and results, and provider-neutral transport types.

- **Owns (chiptunes player):** the host-speaker chiptunes player across its
  worker process boundary — the playback state it publishes, and the track
  preferences that decide which tracks it offers: a favourite is a track the
  person marked, and a disliked track is kept out of the player's track
  discovery. Clients read the playback state the daemon publishes and change
  preferences only through the daemon's chiptunes routes
  (`local/projects/teleclaude/design/architecture/tts-system`). The player's
  process lifecycle stays with `agent_runtime`'s daemon lifecycle, and its
  enablement is configuration.

- **Owns (procedure subscription routing):** reading each published procedure
  subscription — its type patterns, the home kind it answers, the agent
  identity it declares, and the tier it is published in — from the publication
  index `context` publishes; and running,
  on each computer, one platform event consumer that is handed the events its
  own computer emitted whose origin is known, and matches each event's type and
  origin against those subscriptions with `event-catalog`'s type-pattern matcher.
  A procedure answers only events whose origin is of its declared kind, with a
  platform procedure answering events whose origin is none, and a tier-published
  procedure only its own company or person. Each match produces one activation:
  the procedure, the event's origin, the event, the agent identity the
  procedure declares, and the platform's system principal as its origin,
  identified by the event's id, the procedure, and the home so that handling
  the same event again finds the existing activation.
  Routing reads the event's source, origin and subject as its producer stated
  them and never constructs, replaces, or converts any of them; it coordinates
  no computers. An event another computer emitted and an event whose origin is
  unknown produce no activation and record no failure. A submission that fails
  fails the consumer's handling of the event, which the consumer runtime retries
  and parks. The subscription set is held in memory with the identity of the
  index it came from and re-read when the published index changes, so an
  added, edited, or removed subscription takes effect at the next event without
  a restart or a separate trigger. Editing a procedure's subscriptions changes
  its event membership and never the identity of its agent.

- **Also owns (attendance in the activation):** each activation carries the
  attendance its procedure declares, attended when undeclared, read from the
  same published subscription as its agent identity; routing decides nothing
  about it.

- **Also owns (delivery declarations in activations):** carrying the effective
  delivery policy from context's published subscription into the runtime
  activation command, under
  `local/projects/teleclaude/spec/feature/integration/procedure-subscription-routing`.
  Routing derives no defaults and makes no hook eligibility decisions.

- **Also owns (internal handler boundary):** an internal handler receives the
  matched contract alongside the event, so a handler serving several contracts
  knows which one matched when subscriptions overlap.

- **Does not own (procedure activation):** whether a standing agent exists,
  starting or waking it, or the identity it runs under. For each match, the
  activation consumer's first act submits the activation to `agent_runtime` as
  a command addressed to its own computer with a durable operation receipt, so
  the operation exists before any fallible step. It takes no further decision.

- **Owns (conversation entry, adapter side):** recognising an entry identifier
  in what a person sent — however the adapter carries it — and handing it to the
  core; on a per-computer adapter, keeping its lookup of a person's latest
  session by origin metadata; and delivering to the endpoint the core returns
  (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`).
- **Does not own (conversation entry):** resolving an identifier to an endpoint,
  the endpoint registry, the neutral reply, which computer acts, or the
  escalation relay — the core's (`agent_runtime`); whether a home runs a desk
  (`config`); what a desk session may read (`context`).

- **Owns (telling people about events):** the consumers that tell people —
  incident alerts for platform events and subscribed domain events for a
  published domain's events — and what each decides: which events it tells, to
  which recipients within their reach, and when an open matter is closed; the
  incident record of open matters per lifecycle family and thing; the record of
  which selected people a domain event has reached, kept with the event's
  handled record; and composing each message from the event's facts and its type's
  declaration, or its type name when it has none
  (`local/projects/teleclaude/design/architecture/notification-delivery`,
  `local/projects/teleclaude/spec/feature/integration/incident-alerts`,
  `local/projects/teleclaude/spec/feature/integration/subscribed-domain-events`,
  `local/projects/teleclaude/spec/feature/integration/notification-messages`).
  Messages go out through person-addressed delivery; nothing about telling
  people is stored or shown on a shared surface.

- **Does not own (telling people about events):** a person's notification
  interests or whether they select a type (`config`); the lifecycle state
  vocabulary, the type-pattern matcher, or the consumer runtime
  (`event-catalog`); who is a platform administrator or what a principal may
  see (`identity`); what an event means (its producing context).

- **Owns (help-desk Discord surface):** on the master, each hosted desk's
  Discord category and its three channels. This covers the per-person grants
  that turn the desk's scope into Discord visibility and channel abilities,
  re-syncing those grants when a declaration they derive from changes, and
  mirroring each desk session into its own desk's customer-sessions forum
  (`local/projects/teleclaude/spec/feature/integration/discord-admin-reflection-state`).
  A desk forum is no entry point: a post Discord lets through into a desk's
  customer-sessions thread reaches no session.
- **Does not own (help-desk Discord surface):** who is in a desk's scope
  (`identity`); which desks this computer hosts (`agent_runtime`'s endpoint
  registry); whether a home keeps a desk, or a person's Discord binding
  (`config`); a desk session's lifecycle or its escalation relay
  (`agent_runtime`).

- **Owns (Discord message continuity):** the inbound behavior of
  `local/projects/teleclaude/spec/feature/integration/discord-message-continuity`.
  - **Live classification gate.** A guild post is classified as managed or
    unmanaged only once the run's routing attempt has completed and no
    recovery pass is in progress.
  - **Recovery passes.** A pass runs after the routing attempt of each new
    gateway session: the first connection, and every later connection that
    does not resume the previous gateway session. A pass also runs after every
    later publication of routing within the same gateway session. A pass
    covers every thread and Team channel bound to a still-active session, taken
    from the sessions' durable bindings rather than from the routing maps. Each
    recovered message enters the live handling path after classification, with
    the live checks on sender, guild and session.
  - **Ordered handoff.** In a managed place, recovered or live, each input is
    handed to handling only after the handling of the input posted before it
    has concluded: the input was accepted, or its handling failed
    definitively. A place's live input is handed on only once that place's
    recovery has completed in the current gateway session. A place whose
    history read fails holds its live input and retries its recovery, and
    nothing but that recovery moves its cursor.
  - **Exhaustive reads.** A place's recovery has completed only when Discord's
    history after its cursor has been read to the end.
  - **The per-place recovery cursor.** The cursor is the newest Discord
    message in that place whose handling has concluded. It never passes a
    message whose handling has not concluded. A message discarded as
    unmanaged while routing is unknown leaves the cursor where it is, so the
    next pass recovers it. The cursor is durable operational state, kept with
    the adapter's reflection state in the main runtime database, and recovery
    reads only messages after it.
    - A newly bound place starts its cursor at its newest message at binding.
    - A place a recovery pass finds without a cursor is seeded by the
      installation rule below, never earlier than the time it became bound.
    - A place already bound when the capability is installed is seeded by the
      installation's storage migration, from that place's own acceptance
      record. The seed is the place's newest Discord input that the inbound
      queue still retains as accepted.
    - When the queue retains no accepted input for the place, the seed is the
      queue's retention horizon. A message in that place posted after the
      horizon and accepted would still be retained, so every message after the
      horizon was not processed.
    - Nothing is accepted while the daemon is down, so everything posted during
      the installation's own outage stays after the seed.
  - **Recovered-input facts.** The normalized input carries the message's
    original posting time and a recovered mark.
- **Does not own (Discord message continuity):** duplicate suppression at
  acceptance (`local/projects/teleclaude/spec/inbound-queue`), and how a
  recovered input is presented to the agent
  (`local/projects/teleclaude/spec/feature/agent_runtime/session-input-delivery`).

- **Owns (CI run outcomes):** translating a project's relayed GitHub
  workflow-run completions into run outcomes and main-revision green
  announcements
  (`local/projects/teleclaude/spec/feature/integration/ci-run-outcomes`). One
  platform event consumer on each computer is handed the relayed run
  completions its own computer emitted. The ingress emits every relayed event,
  so each completion is translated once in the cluster. The consumer reads from
  GitHub only what the delivery lacks, through the in-process GitHub client, as
  the App the project's configuration names, on the repository it declares:
  - a red run's failed jobs and steps;
  - the branch's last green run of that workflow, and the commits since it;
  - for a green required-check run on main, whether every required check has a
    green run for that revision.
- **Also owns (CI event declarations):** `teleclaude.ci.run.completed`, published
  for every completion, and `teleclaude.ci.revision.passed`, published once per
  main revision. Neither reports a lifecycle state. A run completion is an act
  about one run, and a run on an arbitrary branch says nothing about the health
  of a platform thing, so these events feed no failure correlation and no
  incident alert. A run completed event's subject is the run; a revision passed
  event's subject is the revision. Both have the project as origin. Their ids
  derive from the repository, run and attempt, and from the repository and
  revision. A redelivered completion therefore states the same occurrence, and
  consumers recognise it as a repeat.
- **Does not own (CI run outcomes):** whether a failure files a bug, or what the
  bug records (`workflow`); whether an installation activates a green revision
  (its channel's activation contract); the shape of the CI declaration
  (`config`).

<!-- planned:github-item-acts -->

- **Owns (GitHub work control):** which change to a GitHub-backed work item's
  issue stands for which workflow act, whose changes count — a configured
  person with write access to the repository — and when a change is put back
  and with which reason
  (`local/projects/teleclaude/spec/feature/integration/github-work-control`).
  The handler runs where the item's work runs, on the computer of the session
  holding the item's claim and otherwise on the project's active computer,
  takes each change in the issue's order, and hands each accepted change to
  `workflow`'s update facade as that person.
- **Does not own (GitHub work control):** whether an act is valid or what it
  does (`workflow`); what an issue's fields should hold, how they and their
  history are read, restored and commented (`workflow`'s GitHub adapter
  module); which person a login is
  (`identity`).

<!-- /planned:github-item-acts -->

### Governing designs and decisions

- `local/projects/teleclaude/design/architecture/adapter-client` — the lifecycle of UI adapters and delivery across them
- `local/projects/teleclaude/design/architecture/discord-voice-transport` — the Discord voice connection split between gateway and sidecar
- `local/projects/teleclaude/design/architecture/hook-service` — routing relayed external events to registered handlers
- `local/projects/teleclaude/design/architecture/outbox` — durable queuing of agent hook events
- `local/projects/teleclaude/design/architecture/output-delivery` — how output and footer messages are separated and delivered
- `local/projects/teleclaude/design/architecture/output-sizing` — fitting output to each platform's message limits
- `local/projects/teleclaude/design/architecture/redis-transport` — cross-computer requests and peer discovery over Redis
- `local/projects/teleclaude/design/architecture/telegram-adapter` — Telegram topics as session surfaces and their cleanup
- `local/projects/teleclaude/design/architecture/ui-adapter` — how adapters translate input and render output
- `local/projects/teleclaude/design/architecture/tts-system` — speech output backends, voices and playback
- `local/projects/teleclaude/design/architecture/notification-delivery` — how people are told about events
- `local/projects/teleclaude/adr/0012-master-only-shared-discord-channels` — provisioning shared Discord channels on the master only
- `local/projects/teleclaude/adr/0028-single-lan-bound-ingress` — one ingress computer for external webhooks
- `local/projects/teleclaude/adr/0032-cluster-bus-redis-serves-local-and-cluster` — one Redis serving local and cluster scopes (superseded by ADR-0139)
- `local/projects/teleclaude/adr/0139-each-event-scope-has-its-own-redis` — a local Redis per computer for local events, the shared Redis for cluster events only
- `local/projects/teleclaude/adr/0055-proxy-fronted-ingress-reuse` — the webhook ingress behind a same-host reverse proxy
- `local/projects/teleclaude/adr/0063-core-resolves-admin-reflection-adapter-via-contract` — reaching the admin-reflection adapter through a capability contract
- `local/projects/teleclaude/adr/0084-discord-voice-receive-runs-in-a-node-sidecar` — Discord voice reception in a Node sidecar
- `local/projects/teleclaude/adr/0111-external-events-enter-as-ordinary-platform-events` — external requests entering as platform events
- `local/projects/teleclaude/adr/0120-discord-is-never-a-customer-surface` — Discord as a members-only surface

## See Also

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
