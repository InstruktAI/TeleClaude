---
description: 'Cross-context ubiquitous-language register. Disambiguates terms that appear in multiple bounded contexts so each meaning is explicit and translation rules at boundaries are clear.'
visibility: 'public'
---

# Domain Glossary — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- @docs/project/design/architecture-v2/services.md

## What it is

The cross-context ubiquitous-language register for the platform. Each bounded context has its own internal vocabulary (defined in its per-context domain spec). This document covers terms that appear in MORE THAN ONE bounded context — either with the same meaning that needs canonical naming, or with different meanings that need explicit disambiguation.

Per the Domain-Driven Design principle: inside a context, every term has one meaning. Across contexts, the same word may mean different things, and that's fine — but the differences must be named, not implicit. This glossary names them.

Authors and readers consult this document before introducing a term to a per-context spec. If a term is already here with a different meaning in another context, prefer scoping or renaming over silent reuse.

## Canonical fields

### Disambiguated terms

#### Session

Appears in: `agent_runtime`, `session_ledger`, `identity` (`session_tokens`), `workflow` (consumer only — the next-machine orchestrator dispatches "sessions" but doesn't own the concept).

**One logical concept across `agent_runtime` and `session_ledger`:** a session is the unit of work an agent CLI performs from start to end. `agent_runtime` owns the LIVE session (tmux process, agent CLI, current input/output, current status). `session_ledger` owns the HISTORICAL session (canonical persisted record of what happened during that session, used for replay, search, and audit). The same `session_id` identifies the session across both contexts.

**In `identity`:** "session token" is an authentication credential issued for a session — it is bound to a `session_id` from `agent_runtime` but the token itself is an identity concept, not a session concept. Use the full phrase "session token" inside identity; never shorten to "session".

**Rule:** when a doc uses "session" unqualified, it refers to the `agent_runtime` live entity (and by extension its `session_ledger` historical record). Auth credentials are always qualified as "session token".

#### Artifact

Appears in: `workflow`, `agent_artifacts`. Different concepts. Scope by phrase.

- **Workflow artifact** (or **preparation artifact**, **todo artifact**) — a document produced during a todo's prepare or work phase: `input`, `prd`, `architecture`, `implementation-plan`, `bug`, `quality-checklist`, `design-spec`, `deferrals`, `requirements-review-findings`, `architecture-review-findings`, `plan-review-findings`, `review-findings`. Stored as TEXT in `workflow.artifacts`. `bug` is retained only for legacy read/remove compatibility; new bug todo content is authored in `input`. Authored by prepare/build workers; consumed by reviewers and the next worker in the lifecycle.
- **Agent artifact** — a deployable file or directory under `agents/` that defines an agent's behavior: slash commands, skills, addenda, manifests. Inflated and distributed by `agent_artifacts` to deployed runtime directories (`~/.claude/`, `~/.codex/`, `~/.gemini/`).

**Rule:** never use "artifact" unqualified across contexts. Inside `workflow`, "artifact" alone is fine. Inside `agent_artifacts`, "artifact" alone is fine. In any cross-context doc, qualify.

#### Hook

Appears in: `integration`, `agent_artifacts`. Related concepts; distinct ownership.

- **In `integration`** — a mechanism for receiving external input into the platform. Two sub-types share this word: (1) **inbound webhook** (HTTP POST from external service like Telegram, Discord, WhatsApp), (2) **subprocess hook** (the `telec-hook` binary invoked by an agent CLI, reading payload from stdin). Both produce typed events on the event bus via the same pattern.
- **In `agent_artifacts`** — a configuration entry in an agent CLI's settings (e.g., `~/.claude/settings.json:hooks`) that tells the agent CLI WHEN to invoke an external program. The hook config is deployed by `agent_artifacts`; the program it invokes is `telec-hook` (owned by `integration`).

**Boundary rule:** `agent_artifacts` defines hook configs (the trigger), `integration` handles hook invocations (the response). They share the wire — the deployed hook config points at `integration`'s binary.

**Rule:** in cross-context discussion, distinguish "hook config" (agent_artifacts) from "hook receiver" or "hook invocation" (integration).

#### Channel

Appears in: `integration` (messaging channels), `event_bus` infrastructure (Redis pubsub channels), `config` (deployment release channel). Three different concepts.

- **Messaging channel** — an external delivery target (Telegram chat, Discord forum thread, WhatsApp conversation, email address). Owned by `integration` outbox.
- **Redis channel** — a Redis pubsub topic carrying events between services. Owned by `event_bus` infrastructure; consumed by every service.
- **Release channel** — `alpha` / `beta` / `stable` band that gates a daemon's auto-update behavior. Owned by `config` (per the config-wizard-complete inherited requirements).

**Rule:** always qualify: "messaging channel", "Redis channel", "release channel". Never use "channel" alone.

#### Command

Appears in: `agent_artifacts`, `workflow` (CLI shape, not a domain concept), `telec-cli` infrastructure.

- **Slash command** — an `agent_artifacts` deliverable: a markdown file under `commands/` that defines a slash invocation for an agent CLI (e.g., `/next-prepare`). Deployed to `~/.claude/commands/` etc.
- **CLI command** — a `telec` subcommand surfaced by the `telec-cli` binary (e.g., `telec todo show`). Defined in the CLI source; not a domain concept.
- **Operation command** (rare, internal) — a request emitted into a service's command queue when one exists.

**Rule:** in agent-facing context, "command" alone is acceptable as shorthand for "slash command". In CLI-shape discussion, qualify as "CLI command". In domain specs, "operation command" if referring to internal queues.

#### Agent

Appears in: `agent_runtime`, `agent_artifacts`. Same concept; different lens.

The word "agent" refers to a specific agent CLI instance: Claude, Codex, Gemini, or a future addition. `agent_runtime` cares about the agent as a RUNNING PROCESS (tmux-supervised, currently active, with state). `agent_artifacts` cares about the agent as a DEPLOYMENT TARGET (the runtime directory and config conventions an agent reads).

**Rule:** "agent" is shared vocabulary; both contexts may use it unqualified within their own specs. In cross-context discussion, qualify when ambiguity matters: "agent process" vs "agent runtime target".

#### Token

Appears in: `identity`. Single-context term, listed here because authors sometimes reach for "token" generically.

- **API token** — long-lived credential issued to a machine principal for HTTP API authentication.
- **Session token** — credential bound to a specific `session_id`, carried in `x-session-token` header.

**Rule:** never use "token" alone in cross-context docs. Always qualify with `api` or `session`.

#### Subscription

Appears in: `identity` (person-level subscription preferences for notifications), `integration` (per-recipient subscription cascade for outbound delivery), `agent_runtime` (in-process session-listener subscription for live UI updates).

- **Notification subscription** — `identity` + `integration` together: a person's declared interest in receiving certain event categories on certain channels. `identity` stores the preference; `integration` consumes it during outbox dispatch.
- **Session subscription** — `agent_runtime`-owned: a UI/adapter subscribing to a session's live output. Two axes (listener subscription, direct-link subscription) per `project/spec/session-subscriptions`.

**Rule:** always qualify "subscription" — never use it alone in cross-context docs. The disambiguation matters because session-subscription state is short-lived in-process; notification-subscription state is durable in Postgres.

#### Status

Appears in: virtually every context (todo status, session status, agent availability status, snippet lifecycle status, integration delivery status).

"Status" is generic. Each domain spec uses it freely within its own context. In cross-context docs, qualify: "todo status", "session status", "agent availability status", "snippet lifecycle status", "delivery status".

**Rule:** "status" alone is fine inside a context's own doc. In any cross-context reference, qualify.

#### Phase / Stage

Appears in: `workflow`. Internal-only, but easy to conflate.

- **Stage** — top-level workflow lifecycle band: `draft`, `prepare`, `work`, `integrate`, `delivered`.
- **Phase** — sub-state within a stage: e.g., the `prepare` stage contains phases `intake`, `prd_drafting`, `prd_human_approval`, `architecture_drafting`, ..., `prepared`.

**Rule:** never use "phase" and "stage" interchangeably. Stages contain phases.

### Canonically shared terms (one meaning across contexts)

#### Principal

Owned by `identity`. The authenticated actor making a request. Three subtypes:

- **Human principal** — a person identified by email + role
- **Machine principal** — a daemon / binary process identified by an API token
- **Session principal** — an agent session identified by a session token

Used by other services to authorize calls. Always means the same thing; no disambiguation needed.

#### Project

A project is a directory containing a TeleClaude-managed codebase (has `.teleclaude/` initialized). Project identity is the absolute path. `workflow` owns per-project todos; `agent_artifacts` deploys per-project; `config` overlays per-project. Same concept everywhere.

#### Slug

A kebab-case unique identifier for a todo or roadmap entry. Owned by `workflow`. Referenced by `delivered_by` lists in snippet frontmatter (per `documentation-first-development`).

#### Event (domain event vs integration event)

Per the Domain-Driven Design principle:

- **Domain event** — a fact about something that happened inside a bounded context, expressed in that context's ubiquitous language, named `<context>.<past-tense-verb>` (e.g., `workflow.todo_prepared`, `session_ledger.block_appended`).
- **Integration event** — an event that crosses bounded contexts via Redis. Domain events become integration events when published on the event bus. Same payload; the distinction is whether the consumer is in-process (domain event) or cross-process (integration event).

Owned conceptually by every service that emits one. Carried by the `event_bus` infrastructure crate.

## Allowed values

For the `kind` field of agent artifacts (cross-referenced from `agent_artifacts` domain spec):

- `command` — slash command
- `skill` — invocable skill
- `addendum` — per-agent behavioral shim
- `manifest` — `AGENTS.master.md` for inflation

For the `category` of integration events:

- `inbound` — received from external system (webhook or subprocess hook)
- `outbound` — emitted toward external system (outbox delivery)
- `dlq` — dead-lettered (failed delivery moved to dead-letter)

## Known caveats

- This glossary is a `actual` snippet (committed = canonical). New cross-context terms are added here as they're identified during per-context spec authoring; pull requests touching this file get extra review because the glossary is load-bearing.
- Terms used in a SINGLE context don't belong here — they live in that context's per-context spec glossary section. This document is exclusively for cross-context concerns.
- When a per-context spec wants to introduce a new term that's a synonym for an existing glossary term, the existing term wins. Synonyms get noted in the per-context spec under "Note: synonym for <canonical term>" rather than redefined.
- v1 code may still use terms that conflict with this glossary (e.g., "session" used loosely in v1 internal helpers). Code-level migration to the canonical vocabulary happens gradually as touched; mass-renames are not their own work.
