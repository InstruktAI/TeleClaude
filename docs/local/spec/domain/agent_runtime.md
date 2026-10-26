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

- **Owns:** live-session acceptance and input execution, supervised agent processes, runtime status, and session lifecycle transitions. For scheduled jobs, it also owns the shared outcome/checkpoint handoff and current-record persistence for agent procedures and script results, including agent-report correlation to the currently open run. Each job's procedure or script owns the meaning of its optional checkpoint payload; agent_runtime stores and returns that payload without interpreting it.

- **Owns (endpoints and conversation entry):** the endpoint registry, resolved
  conversation placement, retained bindings and conversational ownership on the
  unique master. Adapters carry provider input, entry identifiers and verified
  channel designation; the core resolves and applies them under
  `local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`.
  The help-desk escalation relay remains owned by
  `local/projects/teleclaude/spec/feature/agent_runtime/help-desk-escalation`.

- **Published contract — hosted desks:** the desks this computer hosts, each
  with its kind, slug and entry identifier. A desk home whose declaration fails
  to load fails the answer with that error; the answer never omits the desk. A
  non-master computer hosts no desks. Consumers act on the answer as given and
  never re-derive hosting from declarations or folders themselves.

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

- **Also owns:** resolving the procedure a dispatch names to one published
  procedure at entry — by its domain-qualified snippet ID, ambiguity and
  absence refused by name — and the session record, title, and live-session
  attribution query that carry and match the procedure as dispatched. It reads
  the publication `context` produces and decides neither reach, layout, nor
  vocabulary.

- **Owns (procedure activation runner):** on the computer that emitted an
  event, one standing agent per procedure per activation home — a company, a
  person, a project, or the platform — as the runner's own behavior, unless the
  procedure declares subject identity (below). The runner
  resolves the agent through the inbound resolve-or-create seam, serialized per
  procedure and home so concurrent activations there cannot both start one.
  When one or more sessions under the system principal already run the
  procedure for the home, it wakes one and starts none; a session carrying
  human lineage is never adopted; when none does, it starts one through the procedure entry
  (`local/projects/teleclaude/spec/feature/agent_runtime/procedure-entry`) —
  naming the procedure, with the home, subject, attendance and delivery facts
  as entry context — in that home: the company's home folder, the person's folder,
  or the project's checkout as `config` answers, or the platform home
  for the platform. A named home absent on the computer fails the activation,
  which is never moved to another home or computer. The session is started
  under the system principal, with its company set only for a company home. The
  procedure event-delivery contract owns the initial canonical brief, hook
  delivery, delivery eligibility and cardinality, and retention of pending
  activations across session transitions
  (`local/projects/teleclaude/spec/feature/agent_runtime/procedure-event-delivery`).
  Activation identity ensures that a repeated activation for the same event,
  procedure, and home reaches the agent once. A
  company-home standing agent may also be started by hand, and nothing
  restricts that; a person-, project-, or platform-home one is started only by
  an activation. Nothing coordinates computers. Each activation is a durable
  operation of its own kind, keyed by the activation's identity, whose
  completed and failed outcome events this context owns and registers;
  completion or failure is recorded once, a failure is never presented as
  success, and it never moves the responsibility to another agent. The agent's
  lifecycle and its handling of later events belong to the procedure it loads.

- **Owns (subject-bound agents):** for a procedure declaring subject identity,
  one agent per procedure, activation home, and the subject the activating
  event names, on the computer that emitted it. The runner records that binding
  on the session it starts, finds the bound session again open or closed,
  delivers to it when open, revives it with its own transcript when it has
  closed, and starts a new bound session in the home when none can continue.
  Resolution is serialized per procedure and home, so concurrent activations
  about one subject start one agent. An activation whose event names no subject
  fails its operation. Everything else — the home folder, the system
  principal, the company of a company home, delivery keyed by the activation,
  and the durable operation — is as for a standing agent.

- **Owns (unattended agents):** a session the activation runner starts for a
  procedure declaring itself unattended records, in the write that creates it,
  that no person watches it, as a fact of that session's record. Its work is a
  run: the runner never revives a closed unattended session, and for a
  procedure declaring subject identity a later activation about that subject
  starts a new bound session instead.
  The fact is the session's own audience statement, beside reach and never
  part of it: the session listing leaves an unattended session out unless the
  caller asks for every session or names the session by id, live session
  updates to people's views carry none, and its output is not eligible for the
  Discord admin lane. Beyond revival,
  attendance changes nothing about which agent answers an activation, where it
  works, what it may do, or how its work is recorded. A session started by
  hand, or by an agent, is attended.

- **Owns (procedure entry):** resolves a published procedure's entry
  declarations, binds and persists the assignment, applies identity-owned
  dispatch privilege, and composes the short reference loader shared by fresh
  entry and continuation. The behavioral contract is
  `local/projects/teleclaude/spec/feature/agent_runtime/procedure-entry`.

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

### Event subjects and origins

Every platform event agent_runtime emits states as its subject and origin what its
act concerned:

- session lifecycle events (a session ended, a restart failed, a bootstrap
  failed): the session, with its recorded configuration subject as origin, or no
  origin when the session has none;
- events a session's own tools emit about its work, such as captured content or
  a raised escalation: the captured item or the escalation, with that session's
  recorded configuration subject as origin and the session among the related
  references;
- daemon and process-supervision events: the computer whose daemon or process
  they concern, with no origin.

A session's end is reported once for every session that ends, whatever folder
it worked in, and the event's type states what kind of session ended: a
help-desk conversation, a person's own conversation, a session the platform or
another session started, or a session whose record establishes none of these.

### Governing designs and decisions

- `local/projects/teleclaude/design/architecture/agent-dispatch` — which agent a fresh session runs, decided at one runtime boundary
- `local/projects/teleclaude/design/architecture/ai-to-ai-dispatch` — how a session starts, watches and is told about the sessions it dispatches
- `local/projects/teleclaude/design/architecture/checkpoint-system` — the debrief prompts a session receives at turn boundaries
- `local/projects/teleclaude/design/architecture/conversation-delivery` — how turns become conversation entries, with their authorship and per-surface generations
- `local/projects/teleclaude/design/architecture/daemon` — what the daemon process runs and supervises
- `local/projects/teleclaude/design/architecture/help-desk-platform` — help-desk entry, the session bound to a conversation, and the desk's documentation depth
- `local/projects/teleclaude/design/architecture/jobs-runner` — the run lifecycle of scheduled jobs and the job contract
- `local/projects/teleclaude/design/architecture/model-launch-resolution` — which model a launched agent process gets
- `local/projects/teleclaude/design/architecture/reminder-service` — session reminders: their record, schedule and firing
- `local/projects/teleclaude/design/architecture/session-lifecycle` — a session's states from creation to cleanup
- `local/projects/teleclaude/design/architecture/session-listeners` — who is told when a watched session changes state
- `local/projects/teleclaude/design/architecture/tmux-management` — the terminal host a session runs in and how input reaches it
- `local/projects/teleclaude/design/architecture/output-polling` — how a session's terminal output is captured
- `local/projects/teleclaude/design/architecture/mcp-registry-resolution` — which MCP servers a session can reach, resolved per project
- `local/projects/teleclaude/design/code-commit` — the sealed commit command and its scope
- `local/projects/teleclaude/design/process-lifecycle` — reaping of leaked processes and the spawn registry
- `local/projects/teleclaude/adr/0018-typed-in-messages-are-first-class-turns` — which inputs count as a session turn
- `local/projects/teleclaude/adr/0037-checkpoint-ledger-separates-commit-detection` — how the commit checkpoint detects committed code
- `local/projects/teleclaude/adr/0038-companion-drift-caught-at-checkpoint` — catching companion-snippet drift at the checkpoint
- `local/projects/teleclaude/adr/0039-guardrails-locked-no-config` — guardrails as a locked engine without per-project quality settings
- `local/projects/teleclaude/adr/0040-guardrails-teleclaude-owned-slimmed` — guardrails' ownership and their substantive scope
- `local/projects/teleclaude/adr/0043-checkpoint-obligations-discharge-on-evidence` — checkpoint obligations discharged by evidence
- `local/projects/teleclaude/adr/0047-commit-gates-in-process-no-stash` — commit gates run in process, never through a stash
- `local/projects/teleclaude/adr/0049-recurring-ticks-via-in-daemon-loop` — recurring job ticks emitted from inside the daemon
- `local/projects/teleclaude/adr/0050-restore-declarative-test-budgets` — the declarative test time budgets
- `local/projects/teleclaude/adr/0064-runner-reaps-process-group-on-normal-exit` — the test and lint runner reaping its process group
- `local/projects/teleclaude/adr/0066-checkpoint-location-axis-in-config-semantics-in-engine` — where a checkpoint action runs, declared per action
- `local/projects/teleclaude/adr/0070-clean-working-tree-floors-the-commit-action-checkpoint` — a clean working tree suppressing the commit checkpoint
- `local/projects/teleclaude/adr/0071-agents-author-their-own-commits` — commit authorship naming the agent that did the work
- `local/projects/teleclaude/adr/0072-commit-author-field-and-session-trailer` — the author field and session trailer the commit surface stamps
- `local/projects/teleclaude/adr/0073-human-involved-is-declared-not-derived` — the human-involvement commit footer as the agent's declaration
- `local/projects/teleclaude/adr/0079-external-session-roots-are-enrolled-not-derived` — how an externally hosted session's process is bound to it
- `local/projects/teleclaude/adr/0086-checkpoint-failures-do-not-invent-work` — checkpoint failures blocking only on established actions
- `local/projects/teleclaude/adr/0087-mechanical-maintenance-executes-in-a-hook` — mechanical maintenance running in the post-commit hook
- `local/projects/teleclaude/adr/0100-commit-maintenance-drains-after-hook-return` — Git returning before commit maintenance completes
- `local/projects/teleclaude/adr/0102-a-telec-wrapper-runs-the-checkout-it-belongs-to` — which checkout's code a telec invocation runs
- `local/projects/teleclaude/adr/0108-the-git-pre-commit-hook-is-the-only-commit-gate` — the pre-commit hook as the only commit gate
- `local/projects/teleclaude/adr/0112-deepseek-fit-judges-runtime-requirements-only` — how DeepSeek runtime fit is judged
- `local/projects/teleclaude/adr/0113-commit-authors-discard-review-candidates` — the author deciding whether a commit owes review
- `local/projects/teleclaude/adr/0123-procedures-are-entrypoints-and-roles-are-explicit-capability-sets` — procedures as session entry points, with roles as explicit capability sets
- `local/projects/teleclaude/adr/0132-an-assignment-carries-only-the-inputs-its-caller-supplied` — an assignment carrying only its caller's inputs
- `local/projects/teleclaude/adr/0033-doc-only-commits-require-independent-review` — doc-only commits owing an independent review

## See Also

- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why each event states the registered project, person, or company its act happened in.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why no subject claims the event concerns no registered home, and an unknown subject makes no claim.

- docs/local/adr/0114-events-take-the-cloudevents-attribute-model.md — why each event names the thing it is about as its subject, separately from its origin.

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
