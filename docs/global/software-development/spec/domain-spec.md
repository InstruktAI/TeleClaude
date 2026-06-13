---
description: "Template every bounded context's canonical domain spec must follow — ubiquitous language, aggregates, events, use cases, context map position."
visibility: 'public'
---

# Domain Spec — Spec

## What it is

The required structure for the canonical domain spec of a bounded context. One spec per context. The spec is the source of truth for what the context does in domain terms — independent of implementation language or technology. Implementation (Python, Rust, anything else) must satisfy the spec; the spec does not describe implementation.

Domain specs are documentation snippets and follow the snippet schema (`general/spec/snippet-authoring-schema`). Project-scoped domain specs live under `docs/project/spec/domain/<context>.md`. Cross-project domain contexts use the owning global domain's `spec/domain/<context>` snippet path when a global snippet is warranted.

Each spec is authored once per bounded context and evolves with the context. New intended state is added by updating the spec and adding the delivering slug to `delivered_by`. Implementation changes that change behavior MUST update the spec.

During a declared migration window, a domain spec describes the platform contract across implementation tracks. If the successor track will diverge from the current track for some aspect of the context, do NOT fork the spec; author a sibling diff companion of `type: spec-diff` capturing only the delta. TeleClaude names that successor track `v2`; other projects must declare their own migration vocabulary before using a successor-track diff. See `software-development/principle/documentation-first-development` section 10 for the spec-diff companion infrastructure and the sections schema.

## Canonical fields

### Frontmatter

```yaml
id: project/spec/domain/<context-name>
type: spec
domain: <domain>
scope: project | global
delivered_by: [<slug>, ...] # optional; present when the spec describes intended state pending delivery
visibility: public
description: <one-line summary of the bounded context>
```

### Required H2 sections

The spec uses `spec` taxonomy but extends the canonical `What it is` / `Canonical fields` shape with domain-specific subsections. The required structure:

**`## What it is`**

One-paragraph description of the bounded context. What domain activity it owns, what state it manages, what it does NOT own. Written in the ubiquitous language of the context.

**`## Canonical fields`**

The structured domain content, organized as `###` subsections in this order:

#### Ubiquitous language

Glossary of terms used INSIDE this bounded context. Each term has one meaning here. Format:

```
**<Term>**
:  <Definition in plain prose, using other glossary terms where applicable>
:  *Synonyms:* <if any>   *Note:* <if the term differs from other contexts>
```

Terms include: entities, value objects, statuses, actions, roles. Avoid implementation terms (table names, function names) unless they ARE the domain term.

#### Aggregates

One subsubsection per aggregate. Each aggregate description includes:

- **Root entity** — the entry point. State changes go through this entity.
- **Contained entities and value objects** — what the aggregate cluster owns.
- **Invariant(s)** — the conditions the root enforces. State outside an invariant is impossible.
- **Identifier** — how aggregates are uniquely identified (UUID, slug, composite key).
- **Lifecycle** — how aggregates come into existence and how they end (creation, deletion, archival).

Example:

```
#### Todo (aggregate)

- **Root:** TodoEntry
- **Contains:** Artifact (input | prd | architecture | implementation-plan | task-plan | bug | quality-checklist | design-spec | deferrals | review-findings), VersionedArtifact, StageState
- **Invariants:**
  - A todo has exactly one current StageState at any moment.
  - An artifact's version history is append-only.
  - An SDLC todo cannot move to `delivered` stage without a non-empty `delivery_commit`.
- **Identifier:** slug (kebab-case, unique per project)
- **Lifecycle:** Created via `telec todo create <slug> <content> [--kind <kind>]` (content required; kind may be omitted only for kind-less intake). Reaches terminal `delivered` after integration for SDLC kinds. Frozen aggregates move to icebox.
```

#### Domain events emitted

One subsubsection per event. Each event description includes:

- **Name** — in the form `<context>.<past-tense-verb>` (e.g., `workflow.todo_prepared`)
- **Emitted when** — the domain condition that triggers emission
- **Payload** — the data carried (field names and types in domain terms; serialization is implementation detail)
- **Consumers** — known downstream contexts that act on this event (cross-reference to their domain specs)
- **Idempotency key** — what makes two emissions of "the same event" the same (so consumers can dedupe)

#### Domain events consumed

One subsubsection per consumed event. Each entry:

- **Name** — the producing context's event (e.g., `integration.hook_received`)
- **Producer** — which context emits it (cross-reference)
- **Reaction** — what this context does in response, in domain terms
- **Failure handling** — what happens if the reaction fails (retry, dead-letter, compensating event)

#### Use cases (index of feature specs)

This section is an INDEX. Each entry references a feature spec snippet at `docs/project/spec/feature/<this-context>/<concept-name>.md` that owns the Gherkin acceptance scenarios for one use case touching this context.

Per `software-development/principle/documentation-first-development`, feature specs are the hub (Gherkin lives there); domain specs are the spokes. The use cases section here lists which feature specs touch this bounded context, with a one-line summary per entry — NOT embedded Gherkin.

Format:

```
- **<feature-concept-name>** — `docs/project/spec/feature/<this-context>/<concept-name>.md` — one-line summary of the use case in domain language
```

Example:

```
- **session-restart-recovery** — `docs/project/spec/feature/agent_runtime/session-restart-recovery.md` — sessions survive daemon restart with reconstructed SessionRuntime actors
- **operation-tracking** — `docs/project/spec/feature/agent_runtime/operation-tracking.md` — long-running task receipts persist across restarts and signal completion via events
```

When a new feature touches this context, a new entry is added here AND the corresponding feature spec is authored at the referenced path.

Detailed Gherkin scenarios live in the feature spec, not here. Detailed JTBD / business value lives in the feature spec, not here. The domain spec stays compact because its job is to describe the bounded context's model + index its features — not to duplicate scenario detail.

#### Context map position

How this bounded context relates to others. For each related context, name the relationship:

- **Partnership** — both contexts evolve together; tight coordination expected.
- **Customer / Supplier** — downstream depends on upstream; upstream commits to a contract for the downstream's needs.
- **Conformist** — downstream accepts whatever upstream provides without translation.
- **Anti-corruption layer (ACL)** — downstream translates upstream's model to keep its own clean. The ACL location is named.
- **Shared kernel** — both contexts share a small common model (use sparingly).
- **Open host service** — this context provides a stable open interface for any consumer.
- **Published language** — the events/contracts this context publishes for any consumer to read.

Format:

```
- **<Other context>** — <relationship>. <One-line description of the relationship's purpose or constraint>.
```

### Optional H2 sections

**`## Allowed values`** — when the context owns enumerations that don't fit naturally inside an aggregate (e.g., role taxonomies, lifecycle hierarchies that cross aggregates).

**`## Known caveats`** — open questions, known design debts, documented exceptions to the discipline. Each caveat names the trade-off and (if applicable) a reference to a slug planning the resolution.

## Allowed values

- Relationship labels in context map: `partnership`, `customer-supplier`, `conformist`, `anti-corruption-layer`, `shared-kernel`, `open-host-service`, `published-language`.

## Known caveats

- Aggregates are sometimes implicit in current code (no single class named `TodoAggregate`). The spec names them in domain terms regardless; identifying aggregates is part of authoring the spec, and may surface refactor opportunities in the implementation.
- Cross-context aggregates do not exist. If two contexts both want to "own" the same concept, the spec authoring process MUST split it — either re-draw the context boundary or model the concept in one context with the other consuming events about it.
- The Gherkin in use cases is for human/agent readability, not directly executable. Domain specs are not test files; the parity harness (`v2-parity-harness` and successors) GENERATES tests from these use cases against both v1 and v2 implementations.
- A bounded context may have multiple aggregates, but each aggregate belongs to exactly one bounded context. Aggregates don't span contexts.
