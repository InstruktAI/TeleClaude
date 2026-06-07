---
id: 'software-development/principle/documentation-first-development'
type: 'principle'
domain: 'software-development'
scope: 'global'
visibility: 'public'
description: 'Documentation leads, implementation catches up. Snippets declare pending deliveries via delivered_by: so the gap stays honest and the design stays shareable.'
---

# Documentation-First Development — Principle

## Principle

Documentation is the source of truth for what the system is AND what it is becoming. Design happens in the document layer first; code catches up. A snippet that describes the intended shape of the system is not a wish or a forecast — it is the design, written down, shareable, reviewable, and binding on what gets built.

For this to work without becoming a fiction, a snippet's `delivered_by:` field carries the honesty signal. When `delivered_by:` is present, the snippet describes intended state — it lists the delivery slugs that will close the gap between the design and the current implementation. When `delivered_by:` is absent, the snippet describes the current platform contract.

When the delivery slugs in `delivered_by:` reach `delivered`, the integrator clears the field. The reconciliation is enforced by the system, not left to memory.

## Rationale

The alternative — designing inside todos, inside PRDs, inside scattered artifacts — fragments the design surface. Each todo's artifacts are local to that todo. Other agents working in parallel can't easily reference them. The orchestrator that needs to coordinate three related deliveries has to read three different PRDs to see the shared design. Conversations about future state degrade into "go read the X artifact in todo Y."

The alternative on the other side — refusing to update docs until code lands — leaves the design unspoken between conception and delivery. The product owner thinks about the future constantly; the agent reading docs sees only the past. There's no shared surface where forward design lives. So forward design ends up in chat, in Slack threads, in mental models that don't propagate.

Doc-first resolves both by making the design space first-class:

- **Shareable.** A pending snippet (with `delivered_by:` set) is a URL all agents can reach. The design lives in one place, not five.
- **Honest.** The `delivered_by:` field prevents confusion. When present, it declares the snippet describes intended state; when absent, it describes current behavior. A reader knows what they are looking at.
- **Reviewable.** Pending snippets get the same review surface as code — pull requests, lint, validation. Bad design gets caught at doc time, before implementation costs are spent.
- **Aligned.** The orchestrator dispatching three related builds points all three at the same pending snippet. The builders read the same design. Their outputs converge.
- **Reconciled.** When delivery lands, the integrator clears `delivered_by:`. Stale "future" doesn't accumulate.

This is the same shape as TDD, schema-first API design, and ADRs. The discipline isn't new — what's new is naming it for documentation, encoding it in frontmatter, and making the reconciliation automatic.

## Implications

The **enforceable rules** of this principle — doc-only work is never a todo,
functionality work authors its snippets first, every behavioral delta is
reflected, a stale current snippet is a defect, delivery clears `delivered_by:` —
live in `general/policy/documentation-discipline`. The **authoring mechanics** —
planned sections, companions, frontmatter, `telec sync` — live in
`general/procedure/doc-snippet-authoring`, and the **field shapes** in
`general/spec/snippet-authoring-schema`. This section states the conceptual
consequences that shape how documentation is organized.

### 1. Discoverability surfaces ownership

`telec docs index` renders the owning slugs inline for every pending snippet — current snippets render with no suffix, a brand-new pending snippet renders with a `(delivered by: <slugs>)` suffix, and a live snippet with an incoming change renders with a `(superseded by: <slugs>)` suffix. The same listing answers "what is the state of this snippet?" and "who is on the hook to close the gap?" without a second lookup.

A worker preparing or building a slug runs `telec docs index --target <slug>` to see exactly which snippets it owns. This is the canonical query that makes the doc-first discipline operational rather than aspirational: the worker asks the system what it has been put on the hook for, and the system answers.

### 2. Domain specs carry `delivered_by:` when their context is being rewritten

A per-context domain spec (see `software-development/spec/domain-spec`) for a service that is being rewritten carries `delivered_by:` listing the slugs that will deliver the rewrite. Workers on the new implementation build against the pending spec. When the new implementation ships and cuts over, the integrator clears `delivered_by:`. The parity check verifies the clear is honest — that the running system actually satisfies what the spec describes.

This is the structural reason a service rewrite is safe under this discipline: the domain spec is the shared design anchor; both the old implementation (in its declining role) and the new one (in its ascending role) must satisfy it; the cutover happens when the new implementation satisfies the same spec the old one satisfies.

### 3. Feature specs are the hub; domain specs are the spokes

Documentation organizes around two snippet kinds with one-directional flow:

- **Feature spec** (the hub) — describes a feature in business-value terms, contains Gherkin acceptance scenarios, points at the bounded contexts it touches. Lives at `docs/project/spec/feature/<context>/<concept-name>.md`. Concept-named, NEVER slug-named — the snippet identity is the domain concept it describes, not the todo that authored or refined it.
- **Domain spec** (the spokes) — describes a bounded context's ubiquitous language, aggregates, events, and design. Its Use cases section indexes the feature specs that touch this context.

Authoring flows from hub to spokes: an intake agent processes a human's input as a feature need (the hub), then identifies and updates the affected domain specs (the spokes). The reverse direction (spokes inferring hubs) is forbidden — domain concepts don't carry business value standalone; that's the feature's job.

#### 3a. Not every todo deserves a feature spec — classify first

Feature specs exist for **user-visible product capabilities**. They are NOT
the default output of every prepared todo. Three categories of work flow
through prepare; only ONE produces a feature spec:

| Category                             | What it is                                                                                                                         | Durable doc home                                            | Feature spec? |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- | ------------- |
| **A. Product capability**            | User-visible business behavior. CRM dedup, pipeline stages, image generation, a new search.                                        | `docs/project/spec/feature/<context>/<concept-name>.md`     | **YES**       |
| **B. Contract / surface refinement** | Agent-facing or operator-facing surface change. New CLI verbs, new service methods, new events, renamed verbs, refined invariants. | Existing domain spec + CLI-surface spec + architecture docs | **NO**        |
| **C. Implementation-only**           | Refactor, migration, tooling, infrastructure with no contract change.                                                              | None — workflow.artifacts only                              | **NO**        |

A Category B or C todo that produces a feature spec is a defect. The
namespace becomes polluted with slug-named non-features, the
`delivered_by` clear ceremony fires on docs nobody needed, and future
readers can no longer tell which feature specs describe real product
capabilities.

#### 3b. Concept-name derivation (Category A only)

The `<concept-name>` in the feature-spec path is the durable domain noun
for the capability — short, noun-shaped, descriptive of what users get,
stable across multiple deliveries that may shape it. Derived from the
capability, NEVER from the todo slug.

- RIGHT: `docs/project/spec/feature/agent_runtime/session-revival.md`
- RIGHT: `docs/project/spec/feature/workflow/multi-pillar-split.md`
- RIGHT: `docs/project/spec/feature/identity/principal-invitation.md`
- WRONG: `docs/project/spec/feature/<context>/<v2-cutover-slug>.md` (todo slug verbatim)
- WRONG: `docs/project/spec/feature/identity/add-invite-flow.md` (verb-led and ephemeral; the durable noun is "principal invitation")

**Smell test.** If the proposed concept name equals, contains, or is an
obvious rewording of the todo slug, you have not named a concept — you
have copied a slug. Stop. Either re-derive the concept name from the
durable capability, or recognize the work is Category B/C and produce no
feature spec at all.

**Tie-breaker — when in doubt, don't author.** A spurious feature spec is
worse than a missing one. A spurious spec lies to future readers about
what's a real product capability. A missing spec for true Category A work
surfaces as a gap that the next delivery in that capability fills
naturally. Default to skip when classification is uncertain.

**`delivered_by` is many-to-many.** A single delivery may shape multiple snippets; a single snippet may be shaped over time by multiple deliveries. The `delivered_by` list accumulates slugs while in flight; each slug clears as it delivers. The `delivered_by` field empties only when every listed slug has delivered.

**The architecture design lives in doc snippets; the `architecture` workflow.artifact is only a thin index/log.** Design decisions that survive delivery land in docs across two locations:

- **Per-context architectural changes** (new aggregates, new events, refined invariants, internal model adjustments) → the affected domain spec snippet at `docs/project/spec/domain/<context>.md`
- **Cross-cutting architectural changes** (new bounded context, communication patterns, transport rules, context-map shifts, deployment shape) → the architecture design docs at `docs/project/design/architecture-v2/*.md`

The doc-snippet updates ARE the design record — they are authoritative. The `architecture` workflow.artifact persists, but only as a thin per-todo audit log: which snippets the architecture phase touched, why, and the `delivered_by` slug set on them. It carries no design body and is never the source of truth. There is no `architecture` snippet kind. Decisions that don't survive (implementation tactic choices, library selection, internal sequencing) stay ephemeral in workflow.artifacts. The architecture phase routes per change: internal-to-context → domain spec; cross-cutting → design doc; or both when a change has both faces — and logs the routing in the thin artifact.

**PRDs do not survive as snippets.** The PRD captures work-guidance for one delivery (MoSCoW, Why, risks). It is scaffolding. It stays a workflow.artifact and retires after delivery. Only the behavioral contract (Gherkin in feature spec) and the design (updates in domain specs) become docs.

### 4. Prepare workers author directly to the docs layer

The intake and architecture phases of the prepare lifecycle write DIRECTLY to docs — feature spec snippets (intake), domain spec snippets and architecture design docs (architecture). No design-bearing workflow.artifact that later "migrates." The doc IS the source; the architecture phase additionally writes a thin index/log artifact recording which snippets it touched.

**Gherkin lives in the feature spec snippet, authored during intake.** There is no separate `test-specs` phase. The intake worker authors business value + Gherkin acceptance scenarios in the same feature spec snippet, in the same phase. The v1 test-specs phase was artifact-shaped ceremony that the hub-and-spoke model removes.

Ephemeral workflow.artifacts (PRD, implementation plan, review findings, drift analysis, deferrals) remain in `workflow.artifacts` because they're process scaffolding, not behavioral contract.

The prepare state machine still has phases; each phase's output shifts to docs (or stays workflow.artifact for the scaffolding). A phase with nothing to author (e.g., architecture phase on a Gherkin-only feature enrichment) produces no doc change and advances naturally.

### 5. Multi-pillar features split at intake

A feature whose acceptance scenarios cross multiple bounded contexts (pillars) gets handled by the intake phase via proactive split:

1. Intake authors ONE feature spec snippet capturing the cross-context business value and end-to-end Gherkin.
2. Intake identifies which contexts the feature touches (the pillars).
3. If the per-pillar slices could deliver independently (the typical case for multi-pillar features), intake recommends `telec todo split`: a container todo holds the feature identity; per-pillar child todos handle each context's implementation slice. Each child carries its own PRD workflow.artifact (its slice's scope) but the children all reference the SAME feature spec via `delivered_by`. The feature spec's `delivered_by` accumulates every child slug.
4. Children deliver independently; the feature spec's `delivered_by:` clears only when ALL children deliver (per the many-to-many accumulation rule above).
5. If the slices MUST land together (e.g., a new event taxonomy where every consumer needs the coordinated update on the same day), intake keeps a single todo with multiple per-context commits. Independence is the discriminator.

The human reviewer confirms the split decomposition before child todos are dispatched. Auto-splitting without review risks fragmenting features the human wanted atomic.

## Tensions

- **Pending snippets that never deliver.** The slug they point to may be deferred, frozen, or abandoned. The author must either revive the delivery path or clear `delivered_by:` and revert the snippet content to reflect current state — design that nobody is actually committing to deliver doesn't belong in the doc layer.

- **Design churn during prepare.** Pending snippets may go through revisions as the PRD iterates; only commit the snippet update when prepare converges on a stable design (typically after spec/plan review), not on every intermediate draft.

- **Cross-context pending snippets.** Snippets describing intent spanning multiple bounded contexts use `delivered_by` to capture every delivering slug; the snippet remains pending until all parts deliver.

- **Product owner anchor vs. agent ground.** Product owners reading pending snippets (with `delivered_by:` set) see forward state; agents making code decisions need current state. The `[delivered_by → slug]` prefix in `telec docs index` keeps the distinction visible. When a human writes "in our system, X works like Y" as a pending snippet, the human asserts design; an agent reading later must check whether `delivered_by:` is present and not assume X works that way today.

- **Doc-first vs. velocity.** Design that only becomes clear by touching the code: add `delivered_by:` to a snippet to mark it pending, attempt the work, revise as you learn, then deliver. The principle does not require omniscience at design time — it requires writing down what you learn AS you learn it, with honesty about what is current and what is intended. For trivial implementation-internal changes (a one-line bug fix with no contract change), the doc layer is not touched; doc-first scales with the size and reach of the change.
