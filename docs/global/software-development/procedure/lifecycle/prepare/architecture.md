---
description: 'Architecture derivation phase. Ground the approved PRD in code reality, author the design directly into the affected domain-spec or architecture design snippets, and write a thin reviewer-approved architecture index artifact for downstream plan derivation.'
visibility: 'public'
---

# Architecture — Procedure

## Required reads

- @~/.teleclaude/docs/general/principle/intelligence-boundaries.md
- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

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
  `docs/project/spec/domain/<context>.md`. Examples: a new aggregate, a new
  event the context emits, a refined invariant, a new ubiquitous-language term
  inside the context, an internal-model adjustment.
- **Cross-cutting architectural changes** → the architecture design docs. A
  genuinely single-document topic may remain
  `docs/project/design/architecture/<topic>.md`; a composite topic uses
  `docs/project/design/architecture/<topic>/overview.md`, with named sibling
  design facets and topic-owned companion assets when useful. Examples: a new
  bounded context, a communication-pattern change, a transport-boundary
  change, a context-map shift, or a deployment-shape change.
- **Ownership rule** → a cross-cutting design doc owns only the relationship
  among contexts. Every behavior, invariant, state transition, vocabulary
  decision, and validation rule still resolves to one context's domain or
  feature spec. A diagram, coordinating flow, runtime host, or shared module
  never becomes the owner merely because it connects the participants.
- **A change with both faces** → updates both. A new event family used across
  contexts adds the event to the producing context's domain spec AND adds it
  to `project/spec/domain/event-catalog` AND may add a new context-map edge if
  the consumer set changes.

Frontmatter `delivered_by` accumulates this slug on EVERY edited snippet.

When the architecture is explored through a shared visual canvas, activate
`software-development/procedure/collaborative-architecture-canvas`. Its canvas
source and optional render are supplementary companions; the design snippets
remain authoritative and carry the normal pending-delivery semantics.

For decisions that DON'T survive delivery (implementation-tactic choices,
library selection, internal sequencing within a build), keep them ephemeral.
Add them to the next phase's `implementation-plan` workflow.artifact or to the
PRD risks section — they're scaffolding, not contract.

The `architecture` workflow.artifact is a thin index/log of the doc-snippet
edits: which snippets were touched, why, and the `delivered_by` slug set on
them. The design content itself lives in the snippets — the snippets are
authoritative; the artifact is a pure audit/index log, never the design body.

### Outcome

Take the approved PRD and ground it in the codebase. Identify which existing
services + event flows the work touches, which cross-cutting concerns are
affected, which new components (if any) need to exist, and how the work
decomposes architecturally. Author durable design decisions DIRECTLY into the
appropriate doc snippets (domain spec, design doc, or both per the routing
above). Note ephemeral tactic decisions on the implementation-plan artifact
(next phase) or in the PRD's brownfield section.

## Preconditions

- `prd` exists, its current digest has an approved `prd_review` verdict, and
  the real human stamped `prd_approved`.

- Slug is active (not icebox, not delivered).
- The codebase is in a state the architecture can ground against. If staleness
  is detected, re-grounding happens before substantive work begins.

## Steps

First read the software-development principles as listed in the software-development baseline that apply to this work with `telec docs get`.

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
- The platform's architectural docs: `project/design/architecture/...` for the
  platform-specific patterns (event-bus, layer-ownership, etc.).
- The relevant platform-quality-flavors (when the flavor set exists for the
  work's needs — API scaffolding, frontend scaffold, CLI scaffold, event-bus
  service patterns, language tooling).
- The architectural defaults principle (already in required reads) sets the
  baseline stance.

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
(per the routing above). The standard reasoning sections — captured in the
snippets, not in the artifact:

| Section | What it captures |
| ------- | ---------------- |

| **Target preservation** | Which approved outcomes and constraints the architecture must preserve, and where implementation reality pressures them. |
| **Current and intended state** | What exists now, what approved pending work credibly changes, and where those sources reinforce or conflict. |
| **Brownfield reconciliation** | The services, modules, events, surfaces, and patterns touched; which are reused, adapted, replaced, or retired, with reasons tied to the target. |
| **Affected services / domains** | Which bounded contexts change and the nature of each change. |
| **Responsibility ownership** | For every changed behavior, invariant, state transition, or vocabulary decision: its single bounded-context owner, its architectural layer inside that context, and the published contract used by every consumer. |
| **Event flow changes** | Events produced or consumed, compatibility implications, and reuse of existing taxonomy where it serves the target. |
| **Surface changes** | User-facing and external surfaces, named by the product outcome and the applicable scaffold or justified alternative. |
| **State ownership** | State introduced or modified, its single owner, and the explicit contracts through which others observe it. |
| **Platform defaults assessed** | Defaults and flavors reused where they fit; gaps, adaptations, and deliberate divergences with their evidenced trade-offs. A missing flavor is a design constraint to resolve, not automatic permission to hack or an automatic veto on the target. |

| **Prior art & adopt-vs-build** | When the design introduces unfamiliar infrastructure or a security boundary: the reference implementations, current vendor documentation, and at least one comparable production architecture surveyed, and the adopt-vs-build decision with its reason. Bespoke infrastructure or a custom security mechanism with no prior-art evidence is a blocking finding (`general/principle/grounding`). |
| **Decomposition** | If the work is non-trivial, a decomposition into architectural units. Each unit is something a plan task can hang off. |
| **Open architectural questions** | Things that couldn't be resolved from PRD + code + defaults; surface to the human for decision. |

### 3. Code-intelligence-driven brownfield analysis

For brownfield work specifically: apply **code-intelligence grounding** when
the codebase is large enough that human eyes would miss connections. This
means querying the code-intelligence layer (when available) for:

- Which paths depend on the modified surface
- Which event consumers will see the new event types
- Which tests cover the affected code
- Implicit cross-service dependencies

When the code-intelligence blueprint is not yet delivered, fall back to manual
grounding (read the source files referenced in PRD, trace imports / event
subscribers / event publishers manually). Note which dependencies you're
confident about and which you're inferring.

### 4. Write the thin architecture index artifact

Author the design content into the affected snippets first (add this slug
to `delivered_by` on every edited snippet).
Then write the thin index artifact:

```
telec todo artifacts write {slug} architecture <content>
```

The artifact is ONLY an index/log: a list of every snippet touched, a
one-line reason per snippet (which architectural change it carries), and the
`delivered_by` slug set on them. It does NOT restate the design body — that
lives in the snippets and is the authoritative record. Snippets whose section
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
On `needs_work` it routes you back here to address the findings; read
`telec todo artifacts read {slug} architecture-review-findings`, update the
architecture artifact to resolve each finding, then advance again.

## Outputs

- **Domain-spec / architecture design-doc snippet updates** — the
  code-grounded design, authored directly into the affected snippets with
  this slug added to `delivered_by`.
- **Thin `architecture` index artifact** — written via
  `telec todo artifacts write {slug} architecture <content>`; logs which
  snippets were touched and why, NOT the design body.
- **`architecture_review` verdict `approve`** is stamped by the reviewer (not
  by this procedure).

## Discipline

Treat status-quo absorption as an architectural defect: a technically coherent
design is still wrong when it quietly narrows the reviewed product target to
what the current modules already make easy.

Follow the discipline procedure: load domain specs before producing or
modifying any artifact, apply the leakage discriminator, respect
auto-remediation boundaries, verify against loaded specs (not memory), walk
the Definition of Done as your review-awareness checklist.

Treat unresolved ownership as a design blocker. Do not choose the caller,
adapter, daemon, scheduler, shared utility, or current file location as a
default owner; resolve the domain meaning first.

## Recovery

- **PRD is ambiguous about architectural implications.** Draft the architecture
  with the most likely interpretation, mark `[inferred-from-prd-gap]` on each
  contested decision, surface the gaps in the artifact's Open architectural
  questions section.
- **Code-intelligence not yet available.** Fall back to manual grounding. Note
  confidence level per major architectural claim. The reviewer pays extra
  attention to claims marked as inferred.
- **Architecture would require a flavor that doesn't exist.** This is a

design fork. Establish whether the approved target requires a reusable
platform capability, can use an existing adjacent pattern with a reasoned
adaptation, or needs a different established solution. Split a platform gap
when it is independently valuable. Escalate only when the surviving paths
change product intent or a human-owned trade-off; do not silently hack around
the absence or treat it as a veto.

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/intake.md
