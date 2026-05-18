---
id: 'software-development/spec/domain-spec'
type: 'spec'
domain: 'software-development'
scope: 'global'
visibility: 'public'
status: 'mixed'
delivered_by: ['snippet-status-framework']
description: 'Template every bounded context''s canonical domain spec must follow — ubiquitous language, aggregates, events, use cases, context map position.'
---

# Domain Spec — Spec

## What it is

The required structure for the canonical domain spec of a bounded context. One spec per context. The spec is the source of truth for what the context does in domain terms — independent of implementation language or technology. Implementation (Python, Rust, anything else) must satisfy the spec; the spec does not describe implementation.

Domain specs are documentation snippets and follow the snippet schema (`general/spec/snippet-authoring-schema`). They live under `docs/project/domain/<context>/spec.md` (or `docs/global/domain/<context>/spec.md` for cross-project domain contexts).

Each spec is authored once per bounded context and evolves with the context. New target state is added by updating the spec under `status: target` with the delivering slug in `delivered_by`. Implementation changes that change behavior MUST update the spec.

## Canonical fields

### Frontmatter

```yaml
id: <domain>/spec/domain/<context-name>
type: spec
domain: <domain>
scope: project | global
status: actual | target | mixed
delivered_by: [<slug>, ...]   # required when status is target or mixed
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
- **Contains:** Artifact (input | prd | architecture | test-specs | implementation-plan | bug | quality-checklist | design-spec | deferrals | review-findings), VersionedArtifact, StageState
- **Invariants:**
  - A todo has exactly one current StageState at any moment.
  - An artifact's version history is append-only.
  - A todo cannot move to `delivered` stage without a non-empty `delivery_commit`.
- **Identifier:** slug (kebab-case, unique per project)
- **Lifecycle:** Created via `telec todo create` or `telec todo dump`. Reaches terminal `delivered` after integration. Frozen aggregates move to icebox.
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

#### Use cases

One subsubsection per use case. Each use case in one of two forms:

**JTBD form (preferred for product-driven use cases):**

```
When <situation>, I want to <motivation>, so I can <expected outcome>.

Domain steps:
1. <step in ubiquitous language>
2. ...

Acceptance:
- <condition that proves the use case is satisfied>
```

**Gherkin form (preferred for technical / event-driven use cases):**

```
Given <context state>
And <additional state>
When <action>
Then <observable outcome>
And <additional outcome>
```

Use cases describe WHAT the system does for whom, not HOW. Implementation details (frameworks, libraries, storage) belong in the implementation architecture docs, not the domain spec.

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

**`## Allowed values`** — when the context owns enumerations that don't fit naturally inside an aggregate (e.g., role taxonomies, status hierarchies that cross aggregates).

**`## Known caveats`** — open questions, known design debts, documented exceptions to the discipline. Each caveat names the trade-off and (if applicable) a reference to a slug planning the resolution.

## Allowed values

- `status` (frontmatter): `actual`, `target`, `mixed` (per `software-development/principle/documentation-first-development`).
- Relationship labels in context map: `partnership`, `customer-supplier`, `conformist`, `anti-corruption-layer`, `shared-kernel`, `open-host-service`, `published-language`.

## Known caveats

- Aggregates are sometimes implicit in current code (no single class named `TodoAggregate`). The spec names them in domain terms regardless; identifying aggregates is part of authoring the spec, and may surface refactor opportunities in the implementation.
- Cross-context aggregates do not exist. If two contexts both want to "own" the same concept, the spec authoring process MUST split it — either re-draw the context boundary or model the concept in one context with the other consuming events about it.
- The Gherkin in use cases is for human/agent readability, not directly executable. Domain specs are not test files; the parity harness (`v2-parity-harness` and successors) GENERATES tests from these use cases against both v1 and v2 implementations.
- A bounded context may have multiple aggregates, but each aggregate belongs to exactly one bounded context. Aggregates don't span contexts.
