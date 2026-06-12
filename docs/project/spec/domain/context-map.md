---
description: "Relationships between the eight bounded contexts — partnership, customer-supplier, ACL, conformist. The system's social graph at the domain level."
visibility: 'public'
---

# Domain Context Map — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- @docs/project/design/architecture-v2/services.md
- @docs/project/spec/domain/glossary.md

## What it is

The relationships between the eight bounded contexts of the platform: which depends on which, who emits events the other consumes, where anti-corruption layers (ACLs) translate between models, and which contexts are partners vs. customer/supplier.

A bounded context is a service. Eight services, ten or so relationships, named explicitly.

**v2 fold (2026-05-18):** `knowledge` and `agent_artifacts` were collapsed into a single `context` bounded context — they share the same change axis (file-based context engineering: docs, skills, commands, agent files). `memory` was added as the 8th service (durable observations, distinct from session_mirrors). Net service count remains 8: workflow, identity, config, agent_runtime, session_mirrors, context, integration, memory.

## Canonical fields

### Visual map

```mermaid
graph TD
    %% Spine contexts
    identity[identity<br/>principals, tokens, auth]
    config[config<br/>effective configuration]

    %% Domain contexts
    workflow[workflow<br/>todos, roadmap, lifecycle]
    context[context<br/>docs+skills+commands+agents]
    agent_runtime[agent_runtime<br/>live sessions, tmux, CLIs, hooks]
    session_mirrors[session_mirrors<br/>eternal text extracts]
    memory[memory<br/>durable observations]
    integration[integration<br/>external HTTP webhooks + outbox]

    %% Spine: every service depends on these
    identity -.->|principal resolution| workflow
    identity -.->|principal resolution| context
    identity -.->|principal resolution| agent_runtime
    identity -.->|principal resolution| integration
    identity -.->|principal resolution| memory
    config -.->|effective config| workflow
    config -.->|effective config| context
    config -.->|effective config| agent_runtime
    config -.->|effective config| integration
    config -.->|effective config| session_mirrors
    config -.->|effective config| memory

    %% External messaging flows through integration → agent_runtime
    %% Agent CLI hooks reach agent_runtime directly via telec-hook IPC (internal — not shown)
    integration ==>|integration.inbox.received<br/>external messaging| agent_runtime

    %% Extract-window: source-side cursor primitive in agent_runtime
    %% Multiple consumers (session_history, memory-miner) call extract-window via CLI
    %% session_history is shown explicitly because it's part of session_mirrors
    agent_runtime -.->|extract-window CLI<br/>session_history consumer| session_mirrors

    %% Operation events
    agent_runtime ==>|operation events| workflow

    %% Workflow → outbound notifications
    workflow ==>|workflow.todo.phase_advanced<br/>workflow.todo.delivered| integration

    %% Context feeds prepare
    context ==>|context selections| workflow

    %% Context deploys hook configs that agent_runtime reads (filesystem-mediated)
    context -.->|deployed hook configs<br/>(filesystem)| agent_runtime

    classDef spine fill:#e0e7ff,stroke:#4338ca
    classDef domain fill:#dcfce7,stroke:#15803d
    class identity,config spine
    class workflow,context,agent_runtime,session_mirrors,memory,integration domain
```

**Legend:**

- Dashed arrows (`-.->`): synchronous in-process function call (the upstream service is depended on as a crate)
- Solid arrows (`==>`): asynchronous event flow via Redis (the downstream context subscribes to the upstream's events)

### Relationships

Each row names one directed relationship: upstream → downstream. Relationship label per the DDD context-map vocabulary.

#### Spine relationships (every domain context depends on these)

| Upstream   | Downstream                | Relationship      | Purpose                                                                                                                                                                                   |
| ---------- | ------------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `identity` | `workflow`                | Customer-Supplier | Workflow asks identity to resolve the calling principal for authorization on todo operations. Identity owns the contract; workflow conforms.                                              |
| `identity` | `context`                 | Customer-Supplier | Knowledge uses principal role + visibility policy to filter snippets at read time.                                                                                                        |
| `identity` | `agent_runtime`           | Customer-Supplier | Agent runtime binds principals to sessions (the principal authoring a session, the session token credentialing live UI access).                                                           |
| `identity` | `integration`             | Customer-Supplier | Integration resolves caller principal on inbound, attaches principal context to dispatched events.                                                                                        |
| `config`   | (all six domain contexts) | Open Host Service | Config publishes effective-configuration values; every context reads what it needs at startup or on demand. Config doesn't know its consumers; consumers know what config keys they need. |

The spine has NO upstream — `identity` and `config` are the platform's foundation. They emit events (auth-related, config-changed) but they don't react to other contexts.

#### Inbound flow (external → domain)

| Upstream      | Downstream      | Relationship       | Purpose                                                                                                                                                                                                                                                                                                                                                  |
| ------------- | --------------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `integration` | `agent_runtime` | Published Language | Integration normalizes EXTERNAL inputs (HTTP webhooks from third-party providers) into typed events. Agent_runtime subscribes to `integration.inbox.received` for inbound messages (Telegram, Discord, WhatsApp) targeted at sessions. Agent CLI hooks are NOT in this relationship — they reach agent_runtime directly via `telec-hook` IPC (internal). |

The v2 correction (refined): in v1, agent CLI hooks went into `hooks/` which entangled with domain logic. The first v2 framing put ALL inbound in integration; that was too broad. The corrected v2 framing places agent CLI hooks in `agent_runtime` (we control agent CLIs) and keeps `integration` for true external providers (we don't control them). See `transport-rules.md` for the change-axis rationale.

#### Session lifecycle flow

| Upstream        | Downstream              | Relationship                               | Purpose                                                                                                                                                                                                                                                                                               |
| --------------- | ----------------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent_runtime` | `session_mirrors`       | Customer-Supplier (via extract-window CLI) | session_mirrors hosts a `session_history` consumer that registers against `agent_runtime.extract-window`, builds mirrors incrementally from rich windows (filtering to user_text + assistant_text). NOT subscribed to `session.ended` for mirror creation — mirror builds up over the session's life. |
| `agent_runtime` | `memory` (memory-miner) | Customer-Supplier (via extract-window CLI) | Intelligence-driven miner consumes extract-window, writes via `telec memories save`. CLI-only.                                                                                                                                                                                                        |
| `agent_runtime` | `workflow`              | Customer-Supplier                          | Long-running operations on sessions (file syncs, builds) emit `operation.completed` events; workflow consumes when an operation completes a todo lifecycle step.                                                                                                                                      |

#### Workflow → outbound notifications

| Upstream   | Downstream    | Relationship      | Purpose                                                                                                                                                                                          |
| ---------- | ------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `workflow` | `integration` | Customer-Supplier | When a todo advances phase or delivers, workflow emits a domain event. Integration's outbox-dispatch subscribes and routes notifications to configured recipients per their channel preferences. |

#### Context → workflow (context engineering)

| Upstream  | Downstream | Relationship      | Purpose                                                                                                                                                                                |
| --------- | ---------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `context` | `workflow` | Customer-Supplier | Context resolves selections (which snippets to load given a todo's slug, agent, role). Workflow's prepare-orchestrator + build workers consume these selections at session-start time. |

#### Codebase blueprint (structural code intelligence)

| Upstream   | Downstream | Relationship                                               | Purpose                                                                                                                                                                                                                                                                                                                                                      |
| ---------- | ---------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `context`  | `workflow` | Customer-Supplier                                          | `context` owns the Blueprint _contract_ (`.teleclaude/blueprint/graph.json` + `manifest.json`, schema, languages, query surface) and supplies its blast-radius to workflow's plan-draft, where the planner derives a change's affected set from structure instead of grepping.                                                                               |
| `workflow` | `context`  | Customer-Supplier (single-writer of a context-owned cache) | Workflow's integrator is the single writer of the Blueprint: on a successful remote-main pull it runs `graphify update` and writes `graph.json` + `manifest.json`. A deliberate divergence from single-state-owner — the Blueprint is a generated cache (not authoritative state) and the integrator is the one actor that knows when `main` became current. |

#### Cross-filesystem coordination

| Upstream  | Downstream      | Relationship                | Purpose                                                                                                                                                                                                                                                        |
| --------- | --------------- | --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `context` | `agent_runtime` | Conformist (via filesystem) | `context` deploys hook configs (e.g., `~/.claude/settings.json:hooks` pointing at `telec-hook`). `agent_runtime` owns `telec-hook` and reads those configs only insofar as the agent CLI invokes the binary. The handshake is filesystem-mediated, not direct. |

#### Memory standalone

| Upstream | Downstream    | Relationship      | Purpose                                                                                                                                                                                             |
| -------- | ------------- | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `memory` | (all callers) | Open Host Service | Memory is queried/written by agents and humans throughout the system. No strong upstream relationship beyond the spine; no strong downstream relationship beyond callers consuming what they query. |

### Anti-corruption layers (v1 → v2 migration)

During the migration window, every v2 service maintains an ACL against its v1 counterpart:

- v2 `workflow` ↔ v1 `teleclaude/core/todos_db` — v2 reads v1 SQLite during the parallel-capable phase; the ACL translates v1 row shape into v2 aggregates. ACL location: `crates/workflow/src/v1_compat.rs` (planned).
- v2 `identity` ↔ v1 `teleclaude/core/db/_tokens.py` + `_sessions.py` — token format and principal-resolution rules differ slightly. ACL planned in `crates/identity/src/v1_compat.rs`.
- v2 `session_mirrors` ↔ v1 `teleclaude/mirrors` + `teleclaude/history` — text extraction translation; the v2 Mirror aggregate is flat (one row per session, no blocks). v1's CLI surface (`telec history list/search/show`) is preserved via Python shim during the parallel-capable phase.
- v2 `context` ↔ v1 `teleclaude/docs_index.py` + `context_selector.py` — selection policy translates v1's accumulated edge cases.
- v2 `integration` ↔ v1 `teleclaude/hooks/` + messaging adapters — both inbound paths and outbox shape need translation.

ACLs disappear when the corresponding cutover lands (`v2-<service>-cutover` todos). Until then, ACLs are explicit translation modules with their own tests.

### External actors

These are NOT bounded contexts (they're outside the platform) but they appear on the map because contexts have relationships with them:

- **Agent CLIs** (Claude Code, Codex, Gemini) — external processes that `agent_runtime` supervises and that `integration` receives hook callbacks from. `agent_artifacts` deploys to their config directories.
- **Messaging providers** (Telegram, Discord, WhatsApp, email) — external systems that send webhooks INTO `integration` and receive outbox deliveries FROM `integration`.
- **GitHub** — external system that sends webhooks INTO `integration` (release notifications, etc.).
- **Frontend (`frontend/`)** — external presentation layer that consumes services via the HTTP API hosted by `telec-api`. Not a bounded context; pure consumer.

### Change-axis rationale

The context map is the answer to "if a change happens, what triggered it?" — the question from `architecture-v2/transport-rules.md`. Each context's change-axis:

- `identity` changes when auth/identity rules change
- `config` changes when configuration shape changes
- `workflow` changes when todo lifecycle changes
- `context` changes when snippet schema or selection policy changes
- `agent_runtime` changes when session lifecycle, tmux orchestration, or supervision changes
- `session_mirrors` changes when block schema or read-model shape changes
- `integration` changes when external protocol (webhook, hook, messaging) changes — irrespective of which external system
- `agent_artifacts` changes when artifact schema or distribution logic changes

When a proposed change crosses two contexts, it's a signal: either the boundary is wrong (re-draw it) OR the change should be split into two coordinated changes (one per context).

## Allowed values

- Relationship labels (per DDD): `partnership`, `customer-supplier`, `conformist`, `anti-corruption-layer`, `shared-kernel`, `open-host-service`, `published-language`.

## Known caveats

- The map is `actual` upon commit. Evolution happens via new commits, not by leaving relationships "target". When a v2 cutover lands and the ACL disappears, this map updates in the same PR.
- New external systems get added as external actors (not contexts) unless they're literally part of our platform.
- A relationship described informally in a per-context spec but not present here is a defect — either add it here or remove it from the per-context spec.
- Cross-context aggregates remain impossible by construction. If two contexts both seem to want the same data, the resolution is to split the data (one context owns, the other consumes events).
