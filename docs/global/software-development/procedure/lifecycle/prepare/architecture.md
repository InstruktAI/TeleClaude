---
description: 'Architecture derivation phase. Ground the approved PRD in code reality and produce a reviewer-approved architecture artifact for downstream test-specs and plan derivation.'
domain: 'software-development'
id: 'software-development/procedure/lifecycle/prepare/architecture'
scope: 'domain'
type: 'procedure'
visibility: 'public'
---

# Architecture — Procedure

## Required reads

- @~/.teleclaude/docs/general/principle/stewardship.md
- @~/.teleclaude/docs/general/principle/calibration.md
- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/software-development/principle/design-fundamentals.md
- @~/.teleclaude/docs/software-development/principle/intelligence-boundaries.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

Your focus this turn is the architecture phase: ground the approved PRD in the
codebase and produce an `architecture` artifact for downstream test-specs and
plan derivation. The wider prepare lifecycle is still yours; this phase is one
focused part of it.

### Outcome

Take the approved PRD and ground it in the codebase. Identify which existing
services and event flows the work touches, which platform-quality-flavors apply,
which new components (if any) need to exist, and how the work decomposes
architecturally. Produce an **architecture artifact** — a code-grounded
technical brief that bridges product intent and implementation plan.

## Preconditions

- `prd` artifact exists and is approved (`prd_approved` stamped by the real human).
- Slug is active (not icebox, not delivered).
- The codebase is in a state the architecture can ground against. If staleness
  is detected, re-grounding happens before substantive work begins.

## Steps

### 1. Load context

Read:

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

Produce an architectural reading of the work. Standard sections:

| Section | What it captures |
| --- | --- |
| **Brownfield assessment** | What exists in the codebase that this work touches. Services, modules, events, surfaces. For greenfield, a brief note that this is new ground. |
| **Affected services / domains** | Which bounded contexts the work changes. For each, the nature of the change (new behavior, modified behavior, new service entirely). |
| **Event flow changes** | Which events this work produces or consumes. New event types, modified event types (with backward-compat plan), reuse of existing taxonomy. |
| **Surface changes** | Which user-facing or external-facing surfaces change. API endpoints, CLI commands, frontend pages — each named by which platform scaffold supplies them. |
| **State ownership** | What new state is introduced or modified. Which service owns it. How other services that need to read it do so (events, documented API). |
| **Platform-quality-flavors applied** | Which existing flavors / scaffolds this work uses. API scaffolding, frontend flavor, CLI command pattern, event-bus service pattern, language tooling, etc. If a needed flavor doesn't exist, that's a blocking finding (don't hack around it). |
| **Architectural defaults alignment** | A brief section noting where the proposed architecture aligns with the defaults principle, and where (if anywhere) it deliberately diverges — with reason. |
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

### 4. Write the architecture artifact

```
telec todo artifacts write {slug} architecture <content>
```

The artifact follows the structure in step 2. Sections that don't apply (e.g.,
"Event flow changes" for purely-UI work) are explicitly noted as N/A — never
silently omitted.

**Architecture is a translation, not an implementation.** Translate product
intent into technical shape. Do not implement, do not write tests, and do not
invent one-off platform patterns when a standard scaffold or flavor should
exist. When a needed scaffold or flavor is missing, surface it as a blocking
finding instead of hacking around it.

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

- **`architecture` artifact** — code-grounded technical brief written via
  `telec todo artifacts write`.
- **`architecture_review` verdict `approve`** is stamped by the reviewer (not
  by this procedure).

## Discipline

Follow the discipline procedure: load domain specs before producing or
modifying any artifact, apply the leakage discriminator, respect
auto-remediation boundaries, verify against loaded specs (not memory), walk
the Definition of Done as your review-awareness checklist.

## Recovery

- **PRD is ambiguous about architectural implications.** Draft the architecture
  with the most likely interpretation, mark `[inferred-from-prd-gap]` on each
  contested decision, surface the gaps in the artifact's Open architectural
  questions section.
- **Code-intelligence not yet available.** Fall back to manual grounding. Note
  confidence level per major architectural claim. The reviewer pays extra
  attention to claims marked as inferred.
- **Architecture would require a flavor that doesn't exist.** This is a
  blocking finding, not a license to hack a one-off. Surface the gap and
  either: (a) recommend the user defer this work until the flavor is built;
  (b) recommend splitting off the flavor-build as its own todo first;
  (c) proceed with explicit human approval to hack a one-off, with the hack
  documented as tech debt.

## See Also

- ~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- ~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/intake.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discipline.md
