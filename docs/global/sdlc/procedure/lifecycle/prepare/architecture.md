---
description: 'Architecture derivation phase. Ground the approved PRD in code reality, author the design directly into the affected domain-spec or architecture design snippets, and write a thin reviewer-approved architecture index artifact for downstream plan derivation.'
visibility: 'public'
role: architect
parameters:
  - name: slug
    required: true
dispatch:
  agent: [claude, codex, gemini, deepseek]
  thinking_mode: slow
---

# Architecture — Procedure

## Required reads

- @~/.teleclaude/docs/general/principle/intelligence-boundaries.md
- @~/.teleclaude/docs/sdlc/principle/architectural-defaults.md
- @~/.teleclaude/docs/sdlc/policy/preparation-artifact-quality.md
- @~/.teleclaude/docs/sdlc/policy/state-storage.md

## Goal

Reconcile the approved better target with implementation reality without
letting the current implementation absorb or narrow that target. Current
patterns are high-value defaults to assess; the approved outcome determines
whether they are reused, adapted, replaced, or retired.

Your focus this turn is the architecture phase: ground the approved PRD in the
codebase, identify which bounded contexts and which cross-cutting concerns the
delivery touches, and author the architectural changes DIRECTLY into the
appropriate doc snippets. The wider prepare lifecycle is still yours; this
phase is one focused part of it.

### Output targets (per `documentation-first-development`)

Architecture is NOT a separate workflow.artifact. Design decisions that survive
delivery land in docs across two locations — route per change:

- **Per-context architectural changes** → the affected domain spec snippet at
  `docs/local/spec/domain/<context>.md`. Examples: a new aggregate, a new
  event the context emits, a refined invariant, a new ubiquitous-language term
  inside the context, an internal-model adjustment.
- **Cross-cutting architectural changes** → the architecture design docs. A
  genuinely single-document topic may remain
  `docs/local/design/architecture/<topic>.md`; a composite topic uses
  `docs/local/design/architecture/<topic>/overview.md`, with named sibling
  design facets and topic-owned companion assets when useful. Examples: a new
  bounded context, a communication-pattern change, a transport-boundary
  change, a context-map shift, or a deployment-shape change.
- **Index rule** → a new design snippet or decision record is listed in the
  domain spec of the context it governs, or in the context map when it is
  cross-cutting, through the same pending carrier (`sdlc/spec/domain-spec`).
- **Ownership rule** → a cross-cutting design doc owns only the relationship
  among contexts. Every behavior, invariant, state transition, vocabulary
  decision, and validation rule still resolves to one context's domain or
  feature spec. A diagram, coordinating flow, runtime host, or shared module
  never becomes the owner merely because it connects the participants.
- **A change with both faces** → updates both. A new event family used across
  contexts adds the event to the producing context's domain spec AND adds it
  to `local/projects/<slug>/spec/domain/event-catalog` AND may add a new context-map edge if
  the consumer set changes.

Author new and changed design material through the pending carriers prescribed
by `general/procedure/doc-snippet-authoring`.

When the architecture is explored through a shared visual canvas, activate
`sdlc/procedure/architecture-canvas`. Its canvas
source and optional render are supplementary companions; the design snippets
remain authoritative and carry the normal pending-delivery semantics.

For decisions that DON'T survive delivery (implementation-tactic choices,
library selection, internal sequencing within a build), keep them ephemeral.
Record them in the thin `architecture` index for the planner; the approved PRD
is not rewritten — they're scaffolding, not contract.

The `architecture` workflow.artifact is a thin index of the doc-snippet edits:
snippet ids, affected sections, their pending carriers and a brief reason each,
plus the delivery reasoning named in step 2. The design content itself lives in
the snippets — the snippets are authoritative; the artifact never restates the
contract they carry.

### Outcome

Take the approved PRD and ground it in the codebase. Identify which existing
services + event flows the work touches, which cross-cutting concerns are
affected, which new components (if any) need to exist, and how the work
decomposes architecturally. Author durable design decisions DIRECTLY into the
appropriate doc snippets (domain spec, design doc, or both per the routing
above). Record ephemeral tactic decisions in the thin `architecture` index for
the planner.

## Preconditions

- `prd` exists, its current digest has an approved `prd_review` verdict, and
  `prd_approved` is current for that digest.

- Slug is active (not icebox, not delivered).
- The codebase is in a state the architecture can ground against. If staleness
  is detected, re-grounding happens before substantive work begins.

## Steps

<!-- @include: docs/snippets/step-role-read.md -->

First read the sdlc principles as listed in the sdlc baseline that apply to this work with `telec docs get`.

### 1. Load context

Apply the artifact-discovery rule from `preparation-artifact-quality`
(`telec todo artifacts list {slug}`) rather than assuming only the list below
exists — read `log` when present, and any other present artifact this
delivery's history left behind.

Read:

- The PRD's authorized horizon, premises, assumptions, exclusions, deferrals,
  and observable outcomes as distinct sources. Do not flatten them into a list
  of requirements with equal authority.
- Observable current product behavior and approved pending work that defines
  the credible intended state. Keep both distinct from internal module shapes.

- The approved `prd` artifact in full.
- Relevant codebase paths the PRD references or implies. For **brownfield**
  work, this includes the existing services / modules / scaffolds the change
  touches. For **greenfield**, this includes adjacent or analogous platform
  code as reference patterns.
- The governing contracts, reached by the walk in `preparation-artifact-quality`
  (Governing contracts); the project's cross-cutting designs among them carry
  the patterns this project has established.
- The relevant platform-quality-flavors (when the flavor set exists for the
  work's needs — API scaffolding, frontend scaffold, CLI scaffold, event-bus
  service patterns, language tooling).
- The architectural defaults principle (already in required reads) sets the
  baseline stance.

### 1a. Ground state and external primitives before any mechanism

Before choosing a mechanism, settle two things from the substrate, as
`general/principle/grounding` directs:

- **Each piece of state the design needs.** Name who decides it, how often it
  changes, and where the platform already keeps facts of that kind — a
  configuration fact, a domain store's record, a runtime coordination value —
  and place it there. A fact decided by intent and changed by a deliberate act
  is configuration, whatever component reads it. Durable state the design
  introduces, relocates or changes is classified and placed under
  `sdlc/policy/state-storage`: its nature, owner and loss cost, then the
  medium, write isolation, scope and lifecycle that follow from them.
- **Each external system the design depends on.** Inventory the primitives it
  offers for the problem: where state can live and who may change it, what
  guarantees its writes give, how it delivers events, and what identity and
  permission facts it exposes. Read them from its current documentation.

Then name the existing in-system path that already does the nearest job and
the external primitive each part of the design rests on. The design builds
only what neither provides.

### 2. Reason through the architecture

Begin from the approved target, then introduce implementation reality. For
each material collision, ask what must change for the target to survive.
Existing patterns and platform defaults are the starting position because they
carry proven value, not because current code has veto authority. Tie every
deliberate divergence to an approved outcome and an evidenced trade-off.

Keep four views distinguishable while reasoning: current product contract,
current implementation, credible intended state, and relevant solution truth.
Record conflicts and assumptions rather than merging them into one “grounded”
answer. Prior art may inform mechanism; it cannot invent product intent.

Produce an architectural reading of the work, then author the durable parts
DIRECTLY into the affected domain-spec or architecture design-doc snippets
(per the routing above). The standard sections split two ways. The resulting
contract — affected services, responsibility ownership, event flow, surface and
state changes — is authored into the snippets. The delivery reasoning —
governing contracts and paradigms, target preservation, current and intended
state, brownfield reconciliation, platform defaults, prior art and
adopt-vs-build, decomposition, open questions — goes to
the thin `architecture` index, where the planner and reviewer read it. Neither
restates the other; live contracts are not decision journals:

| Section | What it captures |
| ------- | ---------------- |

| **Governing contracts** | The section `preparation-artifact-quality` requires: each contract the walk reaches that bears on the work, and how the design honours it or why it departs. |
| **Governing paradigms** | For each concern the design touches, the paradigm that governs it, and where every operation callers see sits within it with what those callers wait for. A structural decision follows `preparation-artifact-quality` (Structural decisions carry architecture review). |
| **Target preservation** | Which approved outcomes and constraints the architecture must preserve, and where implementation reality pressures them. |
| **Current and intended state** | What exists now, what approved pending work credibly changes, and where those sources reinforce or conflict. |
| **Brownfield reconciliation** | The services, modules, events, surfaces, and patterns touched; which are reused, adapted, replaced, or retired, with reasons tied to the target. |
| **Affected services / domains** | Which bounded contexts change and the nature of each change. |
| **Responsibility ownership** | For every changed behavior, invariant, state transition, or vocabulary decision: its single bounded-context owner, its architectural layer inside that context, and the published contract used by every consumer. |
| **Event flow changes** | Events produced or consumed, compatibility implications, and reuse of existing taxonomy where it serves the target. |
| **Surface changes** | User-facing and external surfaces, named by the product outcome and the applicable scaffold or justified alternative. |
| **State ownership and storage** | State introduced or modified, its single owner, and the explicit contracts through which others observe it; for durable state, its classification and placement under `sdlc/policy/state-storage`. |
| **Platform defaults assessed** | Defaults and flavors reused where they fit; gaps, adaptations, and deliberate divergences with their evidenced trade-offs. A missing flavor is a design constraint to resolve, not automatic permission to hack or an automatic veto on the target. |

| **Prior art & adopt-vs-build** | For every external system the design depends on, its primitives inventory from step 1a; and when the design introduces infrastructure or a security boundary of its own: the reference implementations, current vendor documentation, and at least one comparable production architecture surveyed, and the adopt-vs-build decision with its reason. Bespoke infrastructure or a custom security mechanism with no prior-art evidence is a blocking finding (`general/principle/grounding`). |
| **Decomposition** | If the work is non-trivial, a decomposition into architectural units. Each unit is something a plan task can hang off. |
| **Open architectural questions** | Resolve technical uncertainty through evidence and independent challenge; route only human-owned consequences to the human (`general/policy/human-contract`). An unresolved product-intent gap returns to intake. |

### 3. Brownfield blast radius

For brownfield work, derive the affected surface — dependents, event
consumers, implicit cross-service dependencies — under
`sdlc/procedure/blast-radius-discovery`, which owns tool applicability,
freshness and fallback. Keep confirmed dependencies distinct from inferred
ones.

### 4. Write the thin architecture index artifact

Author the design content into the affected snippets first, each through a
pending carrier naming this slug.
Then write the thin index artifact:

```
telec todo artifacts write {slug} architecture <content>
```

The artifact is an index: every snippet id touched with its affected sections,
its pending carrier and a one-line reason (which architectural change it
carries), plus the delivery reasoning from step 2. It does NOT restate the
design body — that lives in the snippets and is the authoritative record. Snippets whose section
doesn't apply (e.g., no "Event flow changes" for purely-UI work) simply aren't
touched; the index records only what changed.

**Architecture is a translation, not an implementation.** Translate product
intent into technical shape. Do not implement, do not write tests, and do not

let a convenient implementation pattern rewrite the approved target. Reuse a
standard scaffold or flavor when it serves the outcome. When it does not, name
the mismatch and resolve it through a grounded adaptation, a separately-owned
platform gap, or an explicit architectural alternative; never improvise a
one-off silently.

### 5. Advance the state machine

When the architecture artifact is written, call:

```
telec todo prepare {slug}
```

The state machine routes the next action. It will direct you to dispatch the
architecture reviewer and tail it. On `approve` it advances to the next phase.
On `needs_work` it routes you back here. Read
`architecture-review-findings` and apply the finding-validation, disposition
and evidence-recording rules in `sdlc/procedure/lifecycle/fix-review-findings`
to the indexed design and its thin `architecture` artifact. Architecture
retains snippet and index authoring, revision validation and advancement. Then
advance again.

## Outputs

- **Domain-spec / architecture design-doc snippet updates** — the
  code-grounded design, authored directly into the affected snippets, each
  through a pending carrier naming this slug.
- **Thin `architecture` index artifact** — written via
  `telec todo artifacts write {slug} architecture <content>`; indexes the
  touched snippets and carries the delivery reasoning, NOT the design body.
- **`architecture_review` verdict `approve`** is stamped by the reviewer (not
  by this procedure).

## Discipline

Treat status-quo absorption as an architectural defect: a technically coherent
design is still wrong when it quietly narrows the reviewed product target to
what the current modules already make easy.

Ground and check the architecture under
`sdlc/policy/preparation-artifact-quality`.

Treat unresolved ownership as a design blocker. Do not choose the caller,
adapter, daemon, scheduler, shared utility, or current file location as a
default owner; resolve the domain meaning first.

## Recovery

- **PRD is ambiguous.** Resolve the ambiguity against the approved intent and
  its sources before deriving further. An unresolved product-intent question
  returns to intake. Technical realization within established intent remains
  architecture's responsibility; ground the choice and record its material
  reason in the architecture index, while the affected snippets carry the
  resulting contract.
- **Architecture would require a flavor that doesn't exist.** This is a

design fork. Establish whether the approved target requires a reusable
platform capability, can use an existing adjacent pattern with a reasoned
adaptation, or needs a different established solution. Split a platform gap
when it is independently valuable. Escalate only when the surviving paths
change product intent or a human-owned trade-off; do not silently hack around
the absence or treat it as a veto.

## See Also

- ~/.teleclaude/docs/sdlc/procedure/lifecycle/prepare/intake.md
