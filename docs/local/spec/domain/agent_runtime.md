---
visibility: internal
description: Frozen v1 ownership anchor for live agent sessions and supervised agent CLI processes.
---

# Agent Runtime Domain Spec — Spec

## What it is

The v1 agent-runtime area owns live agent sessions, tmux process supervision,
agent CLI launch and control, runtime status, and session lifecycle signals.
This repository is a maintenance-only appliance: its feature specs describe the
current contract, and replacement architecture is authoritative only in the
TeleClaudeNext repository.

## Canonical fields

- **Current behavior:** `docs/local/spec/feature/agent_runtime/`.
- **Implementation roots:** `teleclaude/core/session_*`,
  `teleclaude/core/tmux_bridge/`, `teleclaude/cli/tool_commands/sessions.py`,
  and `teleclaude/hooks/`.
- **Maintenance stance:** see `local/projects/teleclaude/spec/domain/glossary`. No forward architecture is
  authored into this domain anchor.
- **Agent CLI hook contracts:** each supported runtime's hook surface — event
  vocabulary, payload shapes, per-event context-injection and activity
  capability, and stdout protocol — is consolidated as third-party
  documentation, one root per runtime. It is the authority for what a runtime
  emits and accepts; the adapters under `teleclaude/hooks/adapters/` implement
  against it and never restate it. Discover with `telec docs index --third-party`
  and fetch with `telec docs get`.

### Ownership boundary

- **Owns:** live-session acceptance and input execution, supervised agent
  processes, runtime status, and session lifecycle transitions.
- **Owns (endpoints and conversation entry):** the core's endpoint registry —
  each person's assistant and each enabled help desk — and the one resolver from
  an entry identifier to an endpoint's working folder and hosting computer;
  creating a session at the resolved endpoint with the endpoint stamped beside
  its origin metadata; the mesh master's durable conversation bindings for
  adapters whose messages reach every computer; the rule that a conversation goes
  to its latest session, the role fallback and the neutral reply; and the
  help-desk escalation relay
  (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`,
  `local/projects/teleclaude/spec/feature/agent_runtime/help-desk-escalation`).
  Adapters carry identifiers, and per-computer adapters look up sessions by
  origin metadata; they hold no routing rules.
- **Does not own:** provider transport or presentation, caller-identity policy,
  todo workflow, or durable historical projections.
- **Owns (voice focus):** the association between one identified human and the
  single live session they are currently listening to. Focus follows that
  human's most recent accepted input across origins; activity that is not
  accepted human input never moves it. An explicit selection overrides the
  derived value without creating agent input, and is durable because selection
  and input are separate acts. An utterance latches the focused session at the
  moment its transmission begins, so a later focus change cannot redirect an
  utterance already under way.
- **Published contracts (voice focus):** a command that sets focus explicitly
  for a human, a query returning the currently focused session for a human, and
  the existing session-input delivery contract through which a closed
  voice-originated utterance is accepted. Integration reaches focus only
  through these; it never reads or writes the association directly.
- **Focus authority is the listening computer.** The record lives with the
  computer that owns the person's voice connection, because that is the one
  deciding what to play. Its derived input ordering comes from cluster session
  snapshots, which already publish the identified human and the time input was
  last accepted; an explicit selection supersedes the derived value until a
  later accepted input from that human.
- **Also published:** a query returning a session's complete user-visible final
  response together with the output version it belongs to; and the session
  observation contract — a peer registers renewable, bounded interest in a live
  session, and on that session's agent stop this runtime sends the observing
  peer a notification naming the session and its output-stop version. The
  runtime publishes both halves; what an observer does with the notification is
  the observer's own contract. The published
  snapshot carries the generated summary and an output digest, neither of which
  is the spoken contract, so this is the contract a remote listener reads. It is
  additive: existing queries and payloads are unchanged.
- **Published contracts:** session commands, queries, and lifecycle signals
  exposed to integration, workflow, identity, and session mirrors.
- **Also owns:** resolving a canonical command name to one corpus document
  at dispatch — a domain-qualified name directly, a bare token to its single
  global match, ambiguity refused by name — and the session record, title, and
  live-session attribution query that carry and match the value as dispatched.
  It reads the corpus `context` publishes and the canonical value the command's
  semantic owner emits, and decides neither reach, layout, nor vocabulary.

<!-- planned-change:procedure-activation-gated-on-company -->
- **Owns (procedure activation runner):** on each computer, one standing agent
  per procedure per company, as the runner's own behavior. The runner resolves
  the agent through the inbound resolve-or-create seam, serialized per
  procedure and company so concurrent activations there cannot both start one.
  When one or more sessions under the system principal already run the
  procedure for the company, it wakes one and starts none; a session carrying
  human lineage is never adopted; when none does, it starts one by dispatching the generic
  procedure-activation command — carrying the procedure's identity and the
  company — in the company's home, under the system principal, with the
  session's company set. The triggering event reaches a new agent as its first
  input through the same session-input delivery that wakes an existing one,
  never as additional startup context. Nothing restricts starting such a
  session by hand, and nothing coordinates computers. Each activation is a
  durable operation of its own kind, whose outcome events
  `agent_runtime.procedure_activation.completed` and
  `agent_runtime.procedure_activation.failed` this context owns and registers;
  completion or failure is recorded once, a failure is never presented as
  success, and it never moves the responsibility to another agent. The agent's
  lifecycle and its handling of later events belong to the procedure it loads.
<!-- change:procedure-activation-gated-on-company -->
- **Owns (procedure activation runner):** on the computer an event originated
  on, one standing agent per procedure per activation subject — a company, a
  person, a project, or the platform — as the runner's own behavior. The runner
  resolves the agent through the inbound resolve-or-create seam, serialized per
  procedure and subject so concurrent activations there cannot both start one.
  When one or more sessions under the system principal already run the
  procedure for the subject, it wakes one and starts none; a session carrying
  human lineage is never adopted; when none does, it starts one by dispatching
  the generic procedure-activation command — carrying the procedure's identity
  and the subject — in the subject's home: the company's home, the person's
  folder, or the project's checkout as `config` answers, or the platform's own
  checkout for the platform. A named home absent on the computer fails the
  activation, which is never moved to another home or computer. The session is
  started under the system principal, with its company set only for a company
  subject. The triggering event reaches a new agent as its first input through
  the same session-input delivery that wakes an existing one, never as
  additional startup context, keyed by the activation's identity so that a
  repeated activation for the same event, procedure, and subject reaches the
  agent once. A company-subject standing agent may also be started by hand, and
  nothing restricts that; a person-, project-, or platform-subject one is
  started only by an activation. Nothing coordinates computers. Each activation
  is a durable operation of its own kind, keyed by the activation's identity,
  whose outcome events `agent_runtime.procedure_activation.completed` and
  `agent_runtime.procedure_activation.failed` this context owns and registers;
  completion or failure is recorded once, a failure is never presented as
  success, and it never moves the responsibility to another agent. The agent's
  lifecycle and its handling of later events belong to the procedure it loads.
<!-- /planned-change:procedure-activation-gated-on-company -->
- **Owns (session company):** a session has a company only when it is created
  with `--company` or started from a session that has one; the company is
  recorded on the session record and carried to every session it starts
  without restating. A company that does not exist is an error and one outside
  the requester's memberships is refused; neither starts a session. A company
  profile is injected into startup context only when the session has a company.
  Standing in a company's project injects none: the startup header derived
  from the project is removed. A human-lineage session's startup context lists
  the person's memberships.
- **Consumes (company):** `identity`'s organizational membership resolution to
  validate a selection and to list memberships; this context never re-derives
  membership.

- **Owns (event subscriptions):** an agent session's standing requests to be
  woken by platform stream events
  (`local/projects/teleclaude/spec/feature/agent_runtime/event-subscriptions`).
  The term is distinct from a procedure's declared event subscriptions, which
  `context` publishes and `integration` routes.
  - **Record.** A subscription is a durable record on the computer that hosts
    its session. It carries the subscribed type, its mode, its narrowing, the
    stream position current when it was created, and the session's principal
    and company, which are fixed for the session's life. The session lists and
    withdraws only its own; its close removes them all.
  - **Consumption.** On each computer, this context reads the platform stream
    through its own consumer, apart from the system pipeline's consumer, and
    acknowledges an event only after every wake that event owes on this
    computer has been handed off. A failure before that is retried, and
    retries exhausted end in the stream's dead-letter path, which announces
    itself. Neither path acknowledges the event as handled.
  - **Match.** An event matches a live subscription when:
    - it entered the stream after the subscription was created, judged by the
      stream's own order rather than by clocks;
    - its type is the subscribed type, and every narrowing value equals the
      named payload field;
    - its declared visibility concerns this computer;
    - `identity`'s reach for the principal at the session's lineage root
      admits the event's subject and carried owner;
    - for a session operating under a company, the event concerns that
      company: its subject is that company, or a project whose carried owner
      is that company. The session company is business scope, so a
      principal's wider reach never widens it
      (`local/projects/teleclaude/spec/feature/agent_runtime/company-scoped-session-context`).
  - **Handoff.** A matched event is handed to the session through control
    delivery once per subscription and event; a repeated handoff of the same
    pair resolves to the first. A single-delivery subscription first records
    the event that claims it, which leaves it live for no other event, and is
    removed once that event's handoff is recorded. Processing that resumes
    after an interruption completes the claimed event's handoff and removal,
    so a single-delivery subscription never wakes for a second event and is
    never spent without its handoff. Delivery past the handoff is control
    delivery's contract.
- **Consumes (event subscriptions):** `event-catalog`'s registry and type
  declarations, read only where an agent's CLI accepts a subscription request,
  which is the one place a request is validated; the envelope facts each event
  carries; and `identity`'s published reach record test, resolved per
  principal and held until a declaration it reads changes. This context
  restates neither the reach rule nor a type's declaration.

### Event subjects

Every platform event agent_runtime emits states as its subject what its act
concerned:

- session lifecycle events (a session ended, a restart failed, a bootstrap
  failed): the session's recorded configuration subject, or no subject when the
  session has none;
- events a session's own tools emit about its work, such as captured content or
  a raised escalation: that session's recorded configuration subject;
- daemon and process-supervision events: no subject.


## See Also

- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why each event states the registered home its act concerned.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why no subject claims the event concerns no registered home, and an unknown subject makes no claim.
- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
