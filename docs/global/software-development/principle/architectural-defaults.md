---
description: 'Architectural defaults every project on this platform should align with: event-driven services, domain-driven boundaries, CLI-first agency, purposeful state, decoupled composition.'
visibility: 'public'
---

# Architectural Defaults — Principle

## Principle

Any project built on this platform defaults to a known set of architectural choices. These are not absolute rules — they can be overridden with explicit reason — but they are the starting position. They exist so projects converge on shared patterns rather than each reinventing structural decisions, and so agents working on these projects can rely on the shape without re-deriving it from scratch.

The defaults answer the question: "in the absence of a specific reason to do otherwise, how is software in this ecosystem structured?"

## Rationale

Convergence on shared architectural patterns produces three compounding wins:

- **Cognitive economy.** Agents (and humans) walking into a project find an expected shape. The expected shape lets them spend reasoning budget on what's specific to this work, not on rediscovering "where state lives" or "how services communicate." A platform without defaults forces re-derivation; the cost falls on every contributor every time.
- **Composability.** When projects follow the same patterns, building blocks become reusable across projects. The platform's CLI scaffold, event bus, identity contract, and scaffolding flavors compose because they all assume the same architectural stance.
- **Quality floor.** Defaults are chosen because they survived encounters with reality. Event-driven decoupling, single state ownership, layered boundaries — these aren't fashion; they're failure-resistant patterns codified across many projects. A project that defaults to them inherits the floor.

The trade is that some work would be cheaper as a one-off hack. The platform accepts that cost because the alternative — every project picking its own structural defaults — produces fragmentation that costs more over time than the occasional save.

## Implications

### 1. Event-driven service composition

Services communicate via events on the platform's bus. New behavior produces and/or consumes events. Direct synchronous service-to-service calls are reserved for cases where latency or transactional semantics genuinely require them, and require explicit justification when chosen over events.

The event bus is the lingua franca between services. Anything that crosses a service boundary should be expressible as an event.

### 2. Domain-driven boundaries

Services are organized as **bounded contexts** representing a domain (sessions, agents, channels, todos, etc.). Service boundaries match domain boundaries. Each service owns its concepts, vocabulary, and storage.

Cross-domain interaction goes through explicit contracts — events, well-defined API surfaces, never by reaching into another service's internals.

### 3. State has a single owner

Each piece of durable state has exactly one owning service. Other services read via documented APIs or by consuming events the owner emits. **No cross-service database access.** State exists where the domain needs it; transient calculations stay stateless. Cached state is explicitly cached, with a documented source-of-truth elsewhere.

This is the structural rule that prevents "two services in two minds about the same data."

### 4. Event taxonomy discipline

Existing event types are reused when applicable. New event types follow established naming and shape conventions. Event taxonomy is coordinated (not ad-hoc per feature). When proposing new events, check the platform's event registry first.

Ad-hoc events bypassing the taxonomy are a defect — they create implicit contracts no one else can discover.

### 5. Layered ownership

Edge (UI / API adapters) → Core (business logic, domain services) → Infrastructure (storage, transport). Each layer respects its boundary:

- Edges **translate** raw inputs into typed core requests; they don't decide.
- Core **decides** based on domain logic; it doesn't translate.
- Infrastructure **executes** mechanically; it doesn't decide.

See `project/design/architecture/layer-ownership` for the platform's concrete layering.

### 6. CLI-first agency

**Every project gets a CLI.** The CLI is the agent's primary interaction surface — new behavior gets a CLI command before (or alongside) any other surface. Agents extend the platform by extending the CLI; humans operate the platform through the CLI.

CLI design follows the platform's chosen pattern (progressive disclosure of help, structured subcommands, idempotent operations, typed arguments). The existing `telec` CLI is the reference shape.

**No MCP servers as a default surface.** MCP-style protocol servers carry their own infrastructure complexity, introduce a separate auth/identity surface, and fragment agent control. The platform consolidates on CLI-first; agents discover capabilities through `--help` and the documented CLI surface. MCP integrations remain available as last-resort tooling for specific external integrations, not as the default agency mechanism.

### 7. Standard scaffolds for surfaces

API endpoints, frontend pages, CLI commands all use the platform's chosen scaffold patterns. No reinvented scaffolding for "this one project." When a flavor doesn't exist for a needed surface, that's a flavor-set TODO — not a license to hack a one-off.

### 8. Identity and session via documented contract

Auth, session, identity-resolution flow through the platform's identity contract (PersonDTO, the session-identity-truth spec, the verify_caller path). No bespoke auth schemes. No invented session models. Identity propagates through documented headers / additional-context, not through ad-hoc state fields.

### 9. Observability as default

- **Structured logs** at decision boundaries. `key=value` format through the project's logging framework, not f-string interpolation, not `print`.
- **Metrics** at request handlers, service boundaries, and decision points.
- **Traces** across service boundaries when the request path is non-trivial.
- No sensitive data in logs (tokens, credentials, PII).
- No truncated identifiers in logs — full UUIDs always.

The system can answer "what happened?" without grep-the-codebase archaeology.

### 10. Configuration via typed schemas

Configuration has a typed shape (Pydantic or equivalent). No env-var-soup; no string-keyed config dicts. Config drift is detectable at startup. New config keys are documented in the platform's config spec.

See the `teleclaude-config` spec as the reference pattern for typed configuration.

### Anti-patterns this principle implicitly forbids

These are concrete moves the defaults reject. Listed explicitly because agents often pattern-match on training-set examples that violate the defaults:

- **Scripts glued together via file handoffs** crossing service boundaries.
- **Direct database access** from one service into another's storage.
- **New HTTP endpoint per behavior** instead of event consumers.
- **Inventing new auth flows** when the identity contract is documented.
- **Storing state in environment variables** as a shortcut.
- **New scaffolding from scratch** when a platform flavor exists.
- **Ad-hoc event types** bypassing the taxonomy.
- **MCP servers as the default agent surface** when CLI extension would do.
- **Print statements** left in production code.
- **Truncated UUIDs** in logs or API responses.

## Tensions

- **Convergence vs flexibility.** Defaults speed common cases but can over-fit when work genuinely calls for a different shape. The resolution: defaults are starting positions, not rules. Override with explicit reason. The principle is "default to these unless you have a specific case to do otherwise" — not "always these regardless."
- **Event-driven vs synchronous semantics.** Some operations need transactional guarantees event-driven composition can't provide. The principle yields here: when the semantics genuinely require synchronous, choose synchronous and document the reason. Don't fight the semantics.
- **CLI-first vs other agent protocols.** MCP and similar protocols have real value in specific contexts (e.g., when integrating with an external tool that only exposes MCP). The principle is "default to CLI; reach for MCP/etc when the external integration demands it" — not "ban MCP."
- **State ownership vs read performance.** Single-state-owner is strict; some read-heavy patterns benefit from replicated state. The principle accepts replicated state as long as the source of truth is explicit and the replication mechanism is documented (events as the replication signal, not direct database reads).
- **Defaults vs project-specific architecture.** This principle is the global default. Specific projects may have additional structural choices that aren't in the global defaults. Those live in project-specific architecture docs (`docs/project/design/architecture/...`), not here.
