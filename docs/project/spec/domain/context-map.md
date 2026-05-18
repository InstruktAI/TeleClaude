---
id: 'project/spec/domain/context-map'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Relationships between the eight bounded contexts — partnership, customer-supplier, ACL, conformist. The system''s social graph at the domain level.'
---

# Domain Context Map — Spec

## Required reads

- @docs/global/software-development/principle/domain-driven-design.md
- @docs/project/design/architecture-v2/services.md
- @docs/project/spec/domain/glossary.md

## What it is

The relationships between the eight bounded contexts of the platform: which depends on which, who emits events the other consumes, where anti-corruption layers (ACLs) translate between models, and which contexts are partners vs. customer/supplier.

A bounded context is a service. Eight services, ten or so relationships, named explicitly.

## Canonical fields

### Visual map

```mermaid
graph TD
    %% Spine contexts
    identity[identity<br/>principals, tokens, auth]
    config[config<br/>effective configuration]

    %% Domain contexts
    workflow[workflow<br/>todos, roadmap, lifecycle]
    knowledge[knowledge<br/>snippet index, selection]
    agent_runtime[agent_runtime<br/>live sessions, tmux, CLIs]
    session_ledger[session_ledger<br/>session history, replay]
    integration[integration<br/>inbound + outbound external]
    agent_artifacts[agent_artifacts<br/>artifact sync, deploy]

    %% Spine: every service depends on these
    identity -.->|principal resolution| workflow
    identity -.->|principal resolution| knowledge
    identity -.->|principal resolution| agent_runtime
    identity -.->|principal resolution| integration
    config -.->|effective config| workflow
    config -.->|effective config| knowledge
    config -.->|effective config| agent_runtime
    config -.->|effective config| integration
    config -.->|effective config| session_ledger
    config -.->|effective config| agent_artifacts

    %% Inbound flow
    integration ==>|integration.inbox.agent_hook_*| agent_runtime
    integration ==>|integration.inbox.received<br/>messaging events| agent_runtime

    %% Session lifecycle flow
    agent_runtime ==>|agent_runtime.session.started/updated/ended| session_ledger
    agent_runtime ==>|operation events| workflow

    %% Workflow → outbound notifications
    workflow ==>|workflow.todo.phase_advanced<br/>workflow.todo.delivered| integration

    %% Knowledge feeds prepare
    knowledge ==>|context selections| workflow

    %% Agent artifacts deploys hook configs that integration receives
    agent_artifacts -.->|deployed hook configs<br/>(filesystem)| integration

    classDef spine fill:#e0e7ff,stroke:#4338ca
    classDef domain fill:#dcfce7,stroke:#15803d
    class identity,config spine
    class workflow,knowledge,agent_runtime,session_ledger,integration,agent_artifacts domain
```

**Legend:**
- Dashed arrows (`-.->`): synchronous in-process function call (the upstream service is depended on as a crate)
- Solid arrows (`==>`): asynchronous event flow via Redis (the downstream context subscribes to the upstream's events)

### Relationships

Each row names one directed relationship: upstream → downstream. Relationship label per the DDD context-map vocabulary.

#### Spine relationships (every domain context depends on these)

| Upstream | Downstream | Relationship | Purpose |
|---|---|---|---|
| `identity` | `workflow` | Customer-Supplier | Workflow asks identity to resolve the calling principal for authorization on todo operations. Identity owns the contract; workflow conforms. |
| `identity` | `knowledge` | Customer-Supplier | Knowledge uses principal role + visibility policy to filter snippets at read time. |
| `identity` | `agent_runtime` | Customer-Supplier | Agent runtime binds principals to sessions (the principal authoring a session, the session token credentialing live UI access). |
| `identity` | `integration` | Customer-Supplier | Integration resolves caller principal on inbound, attaches principal context to dispatched events. |
| `config` | (all six domain contexts) | Open Host Service | Config publishes effective-configuration values; every context reads what it needs at startup or on demand. Config doesn't know its consumers; consumers know what config keys they need. |

The spine has NO upstream — `identity` and `config` are the platform's foundation. They emit events (auth-related, config-changed) but they don't react to other contexts.

#### Inbound flow (external → domain)

| Upstream | Downstream | Relationship | Purpose |
|---|---|---|---|
| `integration` | `agent_runtime` | Published Language | Integration normalizes external inputs (webhooks AND subprocess hooks) into typed events on the bus. Agent_runtime subscribes to relevant event families: `integration.inbox.agent_hook_*` for agent CLI lifecycle signals (session start/end, tool use, etc.), `integration.inbox.received` for inbound messages targeted at sessions. |

The integration → agent_runtime relationship is the v2 architectural correction: in v1, agent CLI hooks went into `hooks/` which entangled with domain logic. In v2, ALL inbound is integration's domain; agent_runtime is downstream and reacts via events.

#### Session lifecycle flow

| Upstream | Downstream | Relationship | Purpose |
|---|---|---|---|
| `agent_runtime` | `session_ledger` | Partnership | These two contexts evolve together as the session story. Agent_runtime emits `session.started`, `session.updated`, `session.ended`; session_ledger appends canonical blocks and projects read models. The session_id namespace is shared. Coordination is tight. |
| `agent_runtime` | `workflow` | Customer-Supplier | Long-running operations on sessions (file syncs, builds) emit `operation.completed` events; workflow consumes when an operation completes a todo lifecycle step. |

#### Workflow → outbound notifications

| Upstream | Downstream | Relationship | Purpose |
|---|---|---|---|
| `workflow` | `integration` | Customer-Supplier | When a todo advances phase or delivers, workflow emits a domain event. Integration's outbox-dispatch subscribes and routes notifications to configured recipients per their channel preferences. |

#### Knowledge → workflow (context engineering)

| Upstream | Downstream | Relationship | Purpose |
|---|---|---|---|
| `knowledge` | `workflow` | Customer-Supplier | Knowledge resolves context selections (which snippets to load given a todo's slug, agent, role). Workflow's prepare-orchestrator + build workers consume these selections at session-start time. |

#### Cross-filesystem coordination

| Upstream | Downstream | Relationship | Purpose |
|---|---|---|---|
| `agent_artifacts` | `integration` | Conformist (via filesystem) | Agent_artifacts deploys hook configs (e.g., `~/.claude/settings.json:hooks` pointing at `telec-hook`). Integration owns `telec-hook` and reads those configs only insofar as the agent CLI invokes the binary. The handshake is filesystem-mediated, not direct. |

### Anti-corruption layers (v1 → v2 migration)

During the migration window, every v2 service maintains an ACL against its v1 counterpart:

- v2 `workflow` ↔ v1 `teleclaude/core/todos_db` — v2 reads v1 SQLite during the parallel-capable phase; the ACL translates v1 row shape into v2 aggregates. ACL location: `crates/workflow/src/v1_compat.rs` (planned).
- v2 `identity` ↔ v1 `teleclaude/core/db/_tokens.py` + `_sessions.py` — token format and principal-resolution rules differ slightly. ACL planned in `crates/identity/src/v1_compat.rs`.
- v2 `session_ledger` ↔ v1 `teleclaude/mirrors` — block normalization happens at the ACL; v1 transcript shapes get translated.
- v2 `knowledge` ↔ v1 `teleclaude/docs_index.py` + `context_selector.py` — selection policy translates v1's accumulated edge cases.
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
- `knowledge` changes when snippet schema or selection policy changes
- `agent_runtime` changes when session lifecycle, tmux orchestration, or supervision changes
- `session_ledger` changes when block schema or read-model shape changes
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
