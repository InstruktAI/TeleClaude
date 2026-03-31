---
id: 'project/design/architecture/layer-ownership'
type: 'design'
domain: 'software-development'
scope: 'project'
description: 'Architectural layer boundaries, ownership rules, and the cross-cutting invariant that downstream layers receive fully resolved inputs.'
---

# Layer Ownership — Design

## Required reads

- @~/.teleclaude/docs/software-development/principle/architecture-boundary-purity.md
- @~/.teleclaude/docs/software-development/principle/design-fundamentals.md

## Purpose

Define the architectural layers of TeleClaude, what each layer owns, and the boundaries between them. This document is the reference for builders and reviewers to verify that code changes respect layer ownership — that logic lives where it belongs, not where it's convenient.

The central invariant: **downstream layers receive fully resolved inputs. They never reach upstream or sideways to resolve their own context.**

## Inputs/Outputs

Each layer has a defined contract for what it receives and what it produces. The direction of data flow establishes ownership.

| Layer            | Receives                                             | Produces                                     |
| ---------------- | ---------------------------------------------------- | -------------------------------------------- |
| Artifact         | Nothing (static)                                     | AI-facing guidance                           |
| Injection        | Raw protocol messages + environment                  | Fully resolved tool calls                    |
| Contract         | Nothing (declarative)                                | Schema that governs what AI clients see      |
| Handler          | Resolved parameters                                  | Tool results                                 |
| Command Pipeline | Edge/handler outputs                                 | Normalized command objects                   |
| Core Services    | Commands, events                                     | State transitions, domain events             |
| Edge             | Raw platform input (headers, webhooks, bot messages) | Typed request metadata + normalized commands |
| CLI / TUI        | API responses, cache snapshots                       | User-facing terminal interface               |
| Infrastructure   | Service-layer requests                               | Storage, execution, transport                |

## Invariants

### The Ownership Rule

Every piece of logic has exactly one layer that owns it. If you're adding logic to a layer, ask: **does this layer own this responsibility?** If the answer requires justification, the logic belongs elsewhere.

### Layer Boundaries

**Artifact Layer**
Owns: AI-facing instructions — commands, skills, agent configurations.
Must never: reference infrastructure details, session mechanics, file paths for internal state, or environment variables. If an artifact needs something from the system, the tooling provides it transparently. The AI is a consumer of contracts, not an implementor of plumbing.

**Injection Layer**
Owns: context resolution at the protocol edge. Session identity, project root, role-based tool filtering, parameter injection. This is where environment awareness lives — nowhere else.
Must never: contain business logic or tool-specific processing. It resolves context and passes it through. Nothing more.

**Contract Layer**
Owns: tool schema declarations — what parameters exist, types, descriptions, required vs optional. The schema is the agreement between AI clients and the system.
Must never: resolve values or contain logic. It declares the shape of the conversation. "Required" means the AI must provide it. "Optional" means the injection layer or the AI may provide it. The contract layer does not decide — it declares.

**Handler Layer**
Owns: tool call processing with fully resolved parameters. Business logic for what happens when a tool is called.
Must never: resolve its own context. If a handler needs a value, it must already be in the parameters — provided by the AI or injected by the injection layer. A handler that reads from environment, filesystem, or other services to fill its own inputs is violating the injection layer's ownership.

**Command Pipeline**
Owns: input normalization and durable execution. All mutations flow through commands. The pipeline ensures idempotent, recoverable execution via the SQLite queue.
Must never: contain adapter-specific logic or bypass the queue for "simple" operations.

**Core Services**
Owns: session management, event bus, output polling, hook processing, coordination logic. The engine that runs the system.
Must never: import adapter-specific code, reference UI concepts, or know about specific transport protocols. Core defines protocols; adapters implement them.

**Edge Layer**
Owns: inbound origin handling for all platforms. Every origin — UI adapters (Telegram, Discord, WhatsApp), API origins (terminal, web), and daemon-internal origins — passes through an edge that normalizes raw platform signals into typed request metadata. Message flows use typed `MessageMetadata` actor fields. Session-creation flows use typed origin metadata objects such as `TerminalOriginMetadata` and `WebOriginMetadata`. Identity resolution reads those typed inputs. The session handler persists the accumulated session view in `origin_metadata`. Downstream layers never assemble origin context themselves.
Must never: contain domain logic or make domain decisions. Edges translate inbound signals — they don't decide. Domain policies live in core. For outbound UX concerns (message rendering, channel management, platform lifecycle), see the [UI Adapter architecture](ui-adapter.md).

**CLI / TUI**
Owns: user-facing terminal interface, argument parsing, display logic.
Must never: access core internals directly. Reads from the API and cache layer. The CLI is a client, not a peer of core.

**Infrastructure**
Owns: tmux execution, SQLite persistence, Redis transport, filesystem operations.
Must never: be accessed directly by handlers, adapters, or artifacts. Each infrastructure concern has an owning service layer that encapsulates access. Direct infrastructure access from upper layers creates invisible coupling.

### Cross-Cutting Rules

1. **No upward resolution.** A layer never reaches into a layer above it to get what it needs. If it doesn't have the data, the layer that owns injection must provide it.
2. **No sideways awareness.** Edges don't know about each other. Handlers don't know which origin triggered them. Core doesn't know which transport delivered the request.
3. **Contracts are the seams.** Layer boundaries are defined by explicit contracts (protocols, schemas, typed interfaces). Crossing a boundary without going through the contract is a violation.

## Primary flows

### Request traversal: AI tool call

```
AI Client
  -> Injection (resolve session identity, project root, filter tools by role)
    -> Handler (process with fully resolved params)
      -> Command Pipeline (normalize to command, enqueue)
        -> Core Services (execute, emit events)
          -> UI Adapter (translate events to platform UX)
```

Each arrow is a boundary crossing. At each crossing, the downstream layer receives everything it needs. It never looks back.

### Request traversal: Human via origin

```
Origin (Telegram, Discord, WhatsApp, Web, Terminal, Daemon)
  -> Edge (normalize platform signals into typed request metadata)
    -> Identity Resolution (resolve human_email, human_role from typed request metadata)
      -> Command Pipeline (normalize to command, enqueue)
        -> Core Services (create/update session, merge session origin sections into origin_metadata)
          -> UI Adapter (translate events to platform UX, where applicable)
```

The edge normalizes request-time identity into typed metadata. Identity resolution reads from that typed payload. Core persists the accumulated session view in `origin_metadata` (the record across all requests). Core never knows which platform originated the request.

## Failure modes

These are the named violations that occur when layer ownership is broken. They are the anti-patterns that builders must avoid and reviewers must catch.

**Symptom Chasing**
A bug appears in one layer. The fix is applied there instead of in the layer that owns the responsibility. The symptom disappears but the architectural violation compounds. _Example: a handler can't find `session_id`, so fallback logic is added to the handler instead of fixing the injection layer._

**Awareness Leak**
A layer is taught something it shouldn't know — an infrastructure detail, an environment variable, a file path for internal state. The layer now has a dependency it didn't need, and every agent session that reads this layer's artifacts inherits that coupling. _Example: a command artifact instructs the AI to read a file from `$TMPDIR` to get its session identity._

**Responsibility Creep**
Logic gradually accumulates in the wrong layer because it's convenient. Each addition is small and "harmless," but the layer's ownership boundary blurs until it owns everything and nothing. _Example: an edge starts making domain decisions because adding one more `if` was easier than routing through core._

**Contract Bypass**
A layer accesses another layer's internals directly instead of going through the contract. The coupling is invisible until something changes, then everything breaks at once. _Example: a handler directly reads from SQLite instead of going through the service layer that owns that data._

## See Also

- docs/project/design/architecture/system-overview.md
- docs/project/design/architecture/daemon.md
- docs/project/design/architecture/ui-adapter.md — outbound UX concerns (rendering, channels, message lifecycle)
