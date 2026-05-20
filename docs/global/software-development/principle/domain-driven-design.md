---
id: 'software-development/principle/domain-driven-design'
type: 'principle'
domain: 'software-development'
scope: 'global'
visibility: 'public'
description: 'Organize systems around bounded contexts, aggregates, ubiquitous language, and domain events. The domain — not the technology — drives structure.'
---

# Domain-Driven Design — Principle

## Principle

The shape of a software system follows the shape of the business problem it serves, not the shape of the technologies it uses. Code, documentation, conversation, and team boundaries align on the **domain** — the real-world activity being supported — and the domain is described in terms a domain expert would recognize.

Domain-Driven Design names the discipline that makes this alignment explicit and durable. Six elements anchor it:

- **Bounded context.** A region of the system where one model of the domain holds and one vocabulary applies. Inside a context, every term has one meaning. Across contexts, the same word may mean different things — and that's fine, because the contexts are isolated.
- **Ubiquitous language.** The vocabulary used inside a bounded context. The same words appear in code identifiers, documentation, test names, and conversation. When a domain expert says "session" and a developer says "session," they mean the same thing because the language was negotiated together.
- **Aggregate.** A cluster of domain objects treated as a single unit for state changes. An aggregate has a root entity, an invariant that must hold across the cluster, and a transactional boundary. State changes go through the root; the root enforces the invariant.
- **Domain event.** A fact about something that happened in the domain, expressed in the ubiquitous language. Events are immutable, carry the data needed by consumers, and form the audit trail of how the domain evolved. They cross context boundaries explicitly.
- **Context map.** The relationships between bounded contexts — who depends on whom, who emits events the other consumes, who has a partnership vs. an anti-corruption layer between them. The map is the system's social graph at the domain level.
- **Anti-corruption layer.** A translation boundary placed between two contexts (often when one is legacy or external) that keeps each context's model clean. The layer translates upstream concepts into the downstream context's terms; the downstream context never imports the upstream model directly.

These elements answer different questions:

- _What is this part of the system about?_ → bounded context, ubiquitous language
- _What state can change atomically here?_ → aggregate, invariants
- _What did the domain do?_ → domain events
- _How do the parts relate?_ → context map, anti-corruption layers

## Rationale

A system organized around domains stays coherent as it grows. A system organized around technical layers (controllers, services, repositories) accumulates accidental complexity at every cross-cut: a new feature touches eight files in eight layers, and the domain logic spreads across all of them. When the domain changes, the changes scatter; when the technology changes, the domain doesn't survive the migration.

DDD inverts this. Each bounded context owns its slice of the domain end-to-end — its model, its storage, its vocabulary, its events. Adding a feature inside one context changes that context only. Changing technology inside one context changes that context only. The domain remains the spine; technology is interchangeable around it.

The compounding wins:

- **Conversations are precise.** Domain experts, product owners, and developers share a vocabulary. A discussion about "completing a session" doesn't require translation.
- **Refactors stay local.** State changes happen inside aggregates, behind their root. Refactoring an aggregate's internals doesn't ripple outward.
- **Events become the integration surface.** Cross-context communication flows through domain events, not direct calls. Each context can evolve internally as long as its event contract holds.
- **Migration becomes possible.** A bounded context can be rewritten — different language, different storage, different framework — without breaking other contexts, because the boundary is the event contract, not the implementation.
- **AI agents can reason locally.** An agent working inside one bounded context loads that context's vocabulary, aggregates, and events. It doesn't need to hold the whole system in head. Smaller, cleaner context windows; better decisions.

The trade-off DDD asks for is upfront design effort. You must identify the contexts, negotiate the language, draw the map. That work is real and it's not free. The payoff is structural durability: a system that ages well instead of one that calcifies.

## Implications

### 1. Every service is a bounded context

In this platform, the unit of bounded context is the **service**. Each service in `services.md` (workflow, identity, config, knowledge, agent_runtime, agent_artifacts, session_ledger, integration) is one bounded context with one model and one vocabulary. Service boundaries are domain boundaries. State ownership is single — no service reaches into another's storage.

This is already codified in `architectural-defaults` ("Services are organized as bounded contexts representing a domain"). DDD names the discipline that backs that default.

### 2. Each bounded context publishes a domain spec

Every bounded context has a canonical domain spec describing what it does in domain terms (see `software-development/spec/domain-spec`). The spec contains the context's ubiquitous language, aggregates and invariants, domain events emitted and consumed, use cases (in JTBD or Gherkin form), and its position on the context map. The spec is authored before implementation, evolves with the context, and is the source of truth for "what does this service do."

Code, tests, and architecture docs all reference the domain spec. When the spec is wrong, fix the spec first. When the code drifts from the spec, the code is the defect.

### 3. Ubiquitous language is enforced

Inside a bounded context, terms have one meaning. Code identifiers, function names, table names, event names, doc snippet titles, and conversation all use the same vocabulary. The vocabulary is defined in the context's domain spec glossary.

If two terms creep in for the same thing (e.g., "session" and "conversation"), one is wrong — pick one and migrate. If one term is being used for two different things in the same context, you've found a hidden distinction that the vocabulary needs to name.

### 4. Aggregates are explicit; transactional boundaries match aggregate boundaries

Each aggregate has a root entity, a defined set of contained entities or value objects, and an invariant the root enforces. State changes go through the root. Transactional boundaries match aggregate boundaries — one transaction touches one aggregate. Cross-aggregate consistency is eventual, mediated by domain events.

This is the rule that prevents the "two services in two minds about the same data" failure mode at the in-process level: even within a single service, aggregates don't share transactional state.

### 5. Domain events are first-class and named in the ubiquitous language

Events carry domain meaning, not technical detail. `workflow.todo_prepared` is a domain event; `database_row_inserted` is not. Event names use past-tense verbs in the context's ubiquitous language. Event payloads carry the data downstream consumers need to act, not the upstream internal state.

The platform's event taxonomy (see `architectural-defaults` rule 4) is a DDD artifact. New events go through the registry; ad-hoc events bypass the taxonomy and are a defect.

### 6. The context map is maintained as a snippet

The relationships between contexts — partnership, customer/supplier, conformist, anti-corruption layer, shared kernel — are explicit and documented. `services.md` is the current platform-level context map; per-context specs reference their upstream and downstream contexts. When a relationship changes (e.g., an anti-corruption layer is removed because the upstream context migrated), the map updates.

### 7. Anti-corruption layers wrap legacy or external concepts

When a bounded context needs to consume from a context with a different (or older) model, an anti-corruption layer translates. v1 → v2 migration is the current and largest example: v2 contexts may temporarily wrap v1 modules with ACLs that translate v1 concepts into v2 vocabulary. The ACL keeps v2's model clean even when v1 is still authoritative for the data.

### 8. Domain-first migration

When a service is rewritten (e.g., v1 Python → v2 Rust), the domain spec is the contract that survives. The rewrite must satisfy the domain spec; the parity check measures the rewrite against the spec, not against the old code line-by-line. Implementation can change freely. The domain cannot.

This is the structural reason rewrites are safe: the domain spec is the invariant target. Without it, a rewrite is unmoored — you can never prove parity because you never wrote down what "parity" meant.

## Tensions

- **DDD vs. speed for small features.** A feature confined to one context doesn't need to revisit the context map. The discipline scales with the size of the change. Tiny changes within a stable context follow existing patterns; large changes or new contexts trigger the full DDD pass (spec author, ubiquitous-language negotiation, event design).

- **Ubiquitous language vs. inherited code.** Legacy code uses terms that may not match the current ubiquitous language. The fix is gradual: when touching a region of code, rename to match the language. Avoid mass-renames as their own work item unless the misalignment is causing active confusion.

- **Bounded contexts vs. shared utilities.** Some code is genuinely shared infrastructure (logging, time, IDs, serialization). It's not a bounded context — it's infrastructure. Place it in shared crates / modules with no domain language. Resist the urge to make every utility into "a service" — services are domain contexts, not utility containers.

- **Aggregate boundaries vs. UI convenience.** A UI form may want to edit data that spans aggregates. The answer is not to widen aggregates to fit the form — it's to split the form's submit into multiple commands, one per aggregate, with the UI orchestrating. This keeps aggregates true to the domain even when interaction patterns span them.

- **Events as integration vs. events as audit log.** Domain events serve both purposes. They're integration messages (subscribers react) AND audit trail (the history of what happened). Design event payloads to satisfy both: enough data for the consumer to act, enough fidelity for the audit reader to understand what occurred.

- **Top-down design vs. emergent design.** Pure top-down (design every context completely before coding) is paralysis. Pure emergent (let structure emerge from code) is the accidental-complexity trap DDD exists to prevent. The middle: name the contexts and the high-level events early, refine aggregates and ubiquitous language as you implement, treat both spec and code as living artifacts that update together.
