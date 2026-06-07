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

### 1. Snippet frontmatter carries `delivered_by:` when pending; absence means current platform contract

A snippet that describes intended state carries a non-empty `delivered_by:` list — the slugs that will close the gap:

```yaml
delivered_by: [slug-a, slug-b]
```

A snippet without `delivered_by:` describes the current platform contract. No additional field is needed to declare the current state.

Validation rules:

- `delivered_by` is an optional non-empty list of slug strings when present.
- `delivered_by` references are lifecycle-owned slug references; snippet validation checks the field shape, and lifecycle callers own relationship integrity.

### 2. The prepare phase authors pending snippets

The prepare orchestrator already runs on `main` with no worktree — it's authorized to write snippets to the canonical doc layer. Authoring or updating the pending snippet for the work being prepared is now a regular prepare deliverable:

- For a `feature`, the PRD includes a "snippets to author or update" section listing the snippets the delivery will produce or change. For a `change` (no PRD — intent is the `input` artifact), the plan-draft step owns the same identification: it names the affected snippets and authors/updates them. No SDLC kind is exempt — every behavioral delta is reflected in the doc layer, or the plan carries an explicit no-doc-impact justification.
- The prepare worker writes the pending snippets to `docs/` as part of preparation, with `delivered_by` pointing at the slug being prepared.
- The plan reviewer verifies the snippets exist, accurately describe the intended state, and that the implementation plan delivers what the snippets promise. This documentation lane is a hard gate: a behavioral delta with neither a snippet update nor a recorded no-doc-impact justification blocks the plan.
- The snippets land on `main` via the normal prepare commit flow, before any work-phase worktree branches off.

The work phase then has the pending snippets as the authoritative design reference. Build workers reference them directly; reviewers check the build against them.

### 3. Delivery clears `delivered_by:`

When a todo reaches `delivered`, the integration lifecycle clears any snippet whose `delivered_by:` list includes the delivered slug before the delivery commit is finalized:

- If the slug was the ONLY entry in `delivered_by:`, the `delivered_by:` field is removed entirely. The snippet now describes the current platform contract.
- If there are still pending slugs in `delivered_by:`, the slug is removed from the list and the snippet remains pending (remaining slugs still in flight).
- `telec sync` does not own this lifecycle mutation; it validates snippet shape, rebuilds indexes, and distributes the source state it receives.

On the same delivery pass the integrator also dissolves the slug's **companions** and **planned sections** into their parents (see §10):

- For each companion `<stem>.<slug>.md` (linked to its parent by filename alone): the companion's content **replaces** the parent file and the companion is deleted.
- For each `<!-- planned:<slug> -->` marker: strip the marker lines; the content stays in place, now live.

The doc layer self-heals to one authoritative snippet per concept — no companions, no markers, no lineage props left.

### 4. Discoverability surfaces ownership

`telec docs index` renders the owning slugs inline for every pending snippet — current snippets render with no suffix, a brand-new pending snippet renders with a `(delivered by: <slugs>)` suffix, and a live snippet with an incoming change renders with a `(superseded by: <slugs>)` suffix. The same listing answers "what is the state of this snippet?" and "who is on the hook to close the gap?" without a second lookup.

A worker preparing or building a slug runs `telec docs index --target <slug>` to see exactly which snippets it owns. This is the canonical query that makes the doc-first discipline operational rather than aspirational: the worker asks the system what it has been put on the hook for, and the system answers.

### 5. Domain specs carry `delivered_by:` when their context is being rewritten

A per-context domain spec (see `software-development/spec/domain-spec`) for a service that is being rewritten carries `delivered_by:` listing the slugs that will deliver the rewrite. Workers on the new implementation build against the pending spec. When the new implementation ships and cuts over, the integrator clears `delivered_by:`. The parity check verifies the clear is honest — that the running system actually satisfies what the spec describes.

This is the structural reason a service rewrite is safe under this discipline: the domain spec is the shared design anchor; both the old implementation (in its declining role) and the new one (in its ascending role) must satisfy it; the cutover happens when the new implementation satisfies the same spec the old one satisfies.

### 6. Hand-edits to snippets follow the same discipline

When you edit a snippet directly (as a human, mid-conversation, refining design), you add `delivered_by:` pointing at the slug that will materialize the change if the edit describes intended state. If no slug exists yet, you create one first (even an empty draft) and reference it.

The product owner habit of "update the doc to anchor my thinking" is welcome — add `delivered_by:` with the delivery slug attached. The anchor is preserved; the reality gap is named.

### 7. A snippet without `delivered_by:` describes the current platform contract

A snippet without `delivered_by:` claims to describe the current system. If the code changes and the snippet doesn't, the snippet is wrong. The reviewer of any code change checks whether the change invalidates any current snippet; if it does, the change either updates the snippet (preferred) or adds `delivered_by:` with the change's slug as the deliverer-of-the-update. Stale current snippets are defects.

### 8. Feature specs are the hub; domain specs are the spokes

Documentation organizes around two snippet kinds with one-directional flow:

- **Feature spec** (the hub) — describes a feature in business-value terms, contains Gherkin acceptance scenarios, points at the bounded contexts it touches. Lives at `docs/project/spec/feature/<context>/<concept-name>.md`. Concept-named, NEVER slug-named — the snippet identity is the domain concept it describes, not the todo that authored or refined it.
- **Domain spec** (the spokes) — describes a bounded context's ubiquitous language, aggregates, events, and design. Its Use cases section indexes the feature specs that touch this context.

Authoring flows from hub to spokes: an intake agent processes a human's input as a feature need (the hub), then identifies and updates the affected domain specs (the spokes). The reverse direction (spokes inferring hubs) is forbidden — domain concepts don't carry business value standalone; that's the feature's job.

#### 8a. Not every todo deserves a feature spec — classify first

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

#### 8b. Concept-name derivation (Category A only)

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

### 9. Prepare workers author directly to the docs layer

The intake and architecture phases of the prepare lifecycle write DIRECTLY to docs — feature spec snippets (intake), domain spec snippets and architecture design docs (architecture). No design-bearing workflow.artifact that later "migrates." The doc IS the source; the architecture phase additionally writes a thin index/log artifact recording which snippets it touched.

**Gherkin lives in the feature spec snippet, authored during intake.** There is no separate `test-specs` phase. The intake worker authors business value + Gherkin acceptance scenarios in the same feature spec snippet, in the same phase. The v1 test-specs phase was artifact-shaped ceremony that the hub-and-spoke model removes.

Ephemeral workflow.artifacts (PRD, implementation plan, review findings, drift analysis, deferrals) remain in `workflow.artifacts` because they're process scaffolding, not behavioral contract.

The prepare state machine still has phases; each phase's output shifts to docs (or stays workflow.artifact for the scaffolding). A phase with nothing to author (e.g., architecture phase on a Gherkin-only feature enrichment) produces no doc change and advances naturally.

### 10. Changing a live snippet — planned sections and companions

A live snippet (one without `delivered_by:`) describes current truth and is
never overwritten in place to describe a change before that change ships. The
change is authored as one of two shapes, both keyed by the delivering `<slug>`,
both reconciled into the parent on delivery.

#### 10a. ADD — planned section

New content (a new scenario, rule, or section) is authored **in context under
its heading**, wrapped in a planned marker:

```
<!-- planned:<slug> -->
...new content...
<!-- /planned:<slug> -->
```

On delivery the marker lines are removed; the content stays in place, now live.
Gherkin appends as more `#### UC-…` blocks and is never reshuffled.

#### 10b. REPLACE — companion

A wholesale rework is authored as a sibling companion `<stem>.<slug>.md` — the
**complete next version** of the parent, not a diff. It is a full snippet: the
same frontmatter as the parent (including its `id`) and a full body. On delivery
its content simply **replaces** the parent file. The link is **the filename
alone** — no field is added to the parent. The companion is located by its
sibling filename and validated as a full snippet, exempt only from the id↔path
and id-collision checks (it deliberately shares the parent's id).

#### 10c. Swap in on delivery

When the slug delivers, the integration machine reconciles the doc layer
programmatically (no agent step), folding the slug's pending state into the live
contract before the integrator's commit:

- Each companion `<stem>.<slug>.md` **replaces** its parent `<stem>.md`; the
  companion is then **deleted**.
- Each `<!-- planned:<slug> -->` block loses its marker lines; the content stays
  in place, now live.
- The slug is removed from any `delivered_by:` list (the field is dropped when the
  slug was its last entry).

Two pending companions on the same parent MUST be dependency-ordered
(`telec todo set-deps B --after A`); delivery is dependency-gated, so they apply
in order, each written against the post-swap parent.

#### 10d. Discoverability

Pending work is **flagged inline, never hidden**. `telec docs index` annotates
each line:

- `(delivered by: <slugs>)` — a brand-new snippet, not yet live (read from its
  own `delivered_by:` field),
- `(superseded by: <slugs>)` — a live snippet with a pending change, **derived**
  from the filesystem (a sibling companion file or an in-body planned marker),
  not from any frontmatter field.

A slug name on an index line is coordination metadata, not actionable content, so
showing it carries no priming risk. The pending **bodies** are what stay
invisible: `telec docs get <id>` strips planned sections (the live contract only),
and `telec docs get <id> --target <slug>` reveals that slug's planned content for
the builder who owns it. Companions never get their own index line. `telec docs
index --target <slug>` narrows the listing to one todo's new snippets.

#### 10e. Migration is just a slug

A v1→v2 migration boundary uses this same mechanism with no special machinery:
the cutover slug (e.g. `v2-config-cutover`) owns the companions
`<stem>.v2-config-cutover.md`. Migration is COMPLETE when that slug delivers and
zero companions remain — the doc layer returns to one authoritative snippet per
concept with no version bookkeeping.

Required on design docs under `docs/project/design/architecture/` (v1),
`architecture-v2/` (v2), and on feature snippets under
`docs/project/spec/feature/`. Path-vs-frontmatter mismatch is a lint
error.

### 11. Multi-pillar features split at intake

A feature whose acceptance scenarios cross multiple bounded contexts (pillars) gets handled by the intake phase via proactive split:

1. Intake authors ONE feature spec snippet capturing the cross-context business value and end-to-end Gherkin.
2. Intake identifies which contexts the feature touches (the pillars).
3. If the per-pillar slices could deliver independently (the typical case for multi-pillar features), intake recommends `telec todo split`: a container todo holds the feature identity; per-pillar child todos handle each context's implementation slice. Each child carries its own PRD workflow.artifact (its slice's scope) but the children all reference the SAME feature spec via `delivered_by`. The feature spec's `delivered_by` accumulates every child slug.
4. Children deliver independently; the feature spec's `delivered_by:` clears only when ALL children deliver (per the many-to-many accumulation rule above).
5. If the slices MUST land together (e.g., a new event taxonomy where every consumer needs the coordinated update on the same day), intake keeps a single todo with multiple per-context commits. Independence is the discriminator.

The human reviewer confirms the split decomposition before child todos are dispatched. Auto-splitting without review risks fragmenting features the human wanted atomic.

### 12. Agent artifacts arrive at delivery, never pre-created

Agent artifacts (commands, skills, agents) are **not** doc snippets and do not carry `delivered_by:`. A snippet can sit on `main` in a pending state because the index flags it; an artifact cannot — it compiles into the live runtime (`~/.claude`, etc.), so a half-authored artifact on `main` is a live, broken tool. Therefore an artifact is authored inside its delivering todo's worktree and reaches `main` only when the integrator delivers that todo. There is no pending-artifact state to mark: until the todo delivers, the artifact does not exist on `main`. Its design intent still lives doc-first — in the governing procedure snippet, which carries the `delivered_by:` — and the thin artifact ships alongside it at delivery.

## Tensions

- **Pending snippets that never deliver.** The slug they point to may be deferred, frozen, or abandoned. The author must either revive the delivery path or clear `delivered_by:` and revert the snippet content to reflect current state — design that nobody is actually committing to deliver doesn't belong in the doc layer.

- **Design churn during prepare.** Pending snippets may go through revisions as the PRD iterates; only commit the snippet update when prepare converges on a stable design (typically after spec/plan review), not on every intermediate draft.

- **Cross-context pending snippets.** Snippets describing intent spanning multiple bounded contexts use `delivered_by` to capture every delivering slug; the snippet remains pending until all parts deliver.

- **Product owner anchor vs. agent ground.** Product owners reading pending snippets (with `delivered_by:` set) see forward state; agents making code decisions need current state. The `[delivered_by → slug]` prefix in `telec docs index` keeps the distinction visible. When a human writes "in our system, X works like Y" as a pending snippet, the human asserts design; an agent reading later must check whether `delivered_by:` is present and not assume X works that way today.

- **Doc-first vs. velocity.** Design that only becomes clear by touching the code: add `delivered_by:` to a snippet to mark it pending, attempt the work, revise as you learn, then deliver. The principle does not require omniscience at design time — it requires writing down what you learn AS you learn it, with honesty about what is current and what is intended. For trivial implementation-internal changes (a one-line bug fix with no contract change), the doc layer is not touched; doc-first scales with the size and reach of the change.
