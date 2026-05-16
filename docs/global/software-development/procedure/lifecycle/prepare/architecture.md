---
id: 'software-development/procedure/lifecycle/prepare/architecture'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Architecture derivation phase. Orchestrator + cross-model peer ground the approved PRD in code reality, name which services, events, scaffolds, and platform building blocks the work uses. Output: an approved architecture artifact for downstream specs and plan derivation.'
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

Take the approved PRD and ground it in the codebase. Identify which existing services and event flows the work touches, which platform-quality-flavors apply, which new components (if any) need to exist, and how the work decomposes architecturally. Produce an **architecture artifact** — a code-grounded technical brief that bridges product intent and implementation plan.

The orchestrator drives this phase. A cross-model peer is dispatched in parallel to verify independently. The output is the technical contract for the work, approved by the human before downstream phases proceed.

## Preconditions

- `prd` artifact exists and is approved (`prd_approved` stamped by the real human).
- Slug is active (not icebox, not delivered).
- The codebase is in a state the architecture can ground against. If staleness is detected, re-grounding happens before substantive work begins.

## Steps

### 1. Load context

The orchestrator reads:

- The approved `prd` artifact in full.
- Relevant codebase paths the PRD references or implies. For **brownfield** work, this includes the existing services / modules / scaffolds the change touches. For **greenfield**, this includes adjacent or analogous platform code as reference patterns.
- The platform's architectural docs: `project/design/architecture/...` for the platform-specific patterns (event-bus, layer-ownership, etc.).
- The relevant platform-quality-flavors (when the flavor set exists for the work's needs — API scaffolding, frontend scaffold, CLI scaffold, event-bus service patterns, language tooling).
- The architectural defaults principle (already in required reads) sets the baseline stance.

### 2. Dispatch peer for independent grounding

The orchestrator dispatches a cross-model peer with the same inputs (PRD + named codebase paths + architectural defaults). The peer's brief: load the architecture skill, reason through the same architectural decisions independently, output findings in its session.

```
telec sessions run \
  --command /next-prepare-architecture \
  --agent codex \
  --args {slug} \
  --detach
```

The orchestrator does not wait. It proceeds with its own architectural reasoning in parallel.

### 3. Reason through the architecture

The orchestrator (and the peer, independently) produces an architectural reading of the work. Standard sections:

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

### 4. Deferred tailing and discussion

The orchestrator continues its own work. When the peer signals it has finished, the orchestrator tails the peer's output **only when its own architectural reasoning is at a natural stopping point**. A peer signal does not interrupt focus.

Once both perspectives are available, the orchestrator reads the peer's architectural reading and engages with it via messages: surfaces where the readings agree, where they diverge, what new material the peer surfaced. Engagement uses the discussion register (respond with reasoning, not Q&A). The discussion ends when both sides exhaust.

### 5. Code-intelligence-driven brownfield analysis

For brownfield work specifically: the orchestrator and peer apply **code-intelligence grounding** when the codebase is large enough that human eyes would miss connections. This means querying the code-intelligence layer (when available) for:

- Which paths depend on the modified surface
- Which event consumers will see the new event types
- Which tests cover the affected code
- Implicit cross-service dependencies

When the code-intelligence blueprint is not yet delivered, the orchestrator falls back to manual grounding (read the source files referenced in PRD, trace imports / event subscribers / event publishers manually). The peer does the same independently. Both note which dependencies they're confident about and which they're inferring.

### 6. Write the architecture artifact

The orchestrator authors the architecture artifact synthesizing its own reasoning, the peer's contribution, and the discussion outcomes:

```
telec todo artifacts write {slug} architecture <content>
```

The artifact follows the structure in step 3. Sections that don't apply (e.g., "Event flow changes" for purely-UI work) are explicitly noted as N/A — never silently omitted.

**Architecture is a translation, not an implementation.** Translate product intent into technical shape. Do not implement, do not write tests, and do not invent one-off platform patterns when a standard scaffold or flavor should exist. When a needed scaffold or flavor is missing, surface it as a blocking finding instead of hacking around it.

### 7. Independent review

The orchestrator dispatches the architecture reviewer:

```
telec sessions run --command /next-review-architecture --args {slug} --agent codex
```

The reviewer reads the architecture artifact against the PRD, the architectural defaults, the existing codebase patterns, and the platform-quality-flavors. Produces a verdict: `approve | changes_requested` with findings.

The orchestrator integrates the verdict:

- `approve` → proceed to step 8.
- `changes_requested` → revise the architecture against findings; re-dispatch reviewer.

### 8. Present for human approval

When the reviewer's verdict is `approve` and findings are addressed, the orchestrator presents the architecture artifact to the human. Calibration applies — register matches PersonDTO proficiency.

The human either:

- **Confirms** → orchestrator stamps `architecture_approved`. Phase complete.
- **Refines** → orchestrator captures delta, may re-engage the peer if the delta opens substantial new architectural ground, regenerates the architecture artifact, presents again.

### 9. Hand off

Once `architecture_approved` is stamped, the architecture phase is done. Downstream phases (test specs, plan) consume the approved architecture artifact alongside the PRD.

## Outputs

- **`architecture` artifact** — code-grounded technical brief.
- **Reviewer verdict** stamped: `architecture_review_verdict: approve`.
- **`architecture_approved` stamp** — recorded by the orchestrator after human confirmation.
- Session transcripts for the orchestrator and the peer carry the durable trace of the architectural reasoning.

## Recovery

- **Peer dispatch fails or returns unusable output.** Orchestrator continues solo; notes the missing peer perspective in the architecture artifact. Reviewer still runs independently and provides the verification.
- **PRD is ambiguous about architectural implications.** Orchestrator drafts the architecture with the most likely interpretation, marks `[inferred-from-prd-gap]` on each contested decision, surfaces the gaps in the artifact's Open architectural questions section.
- **Code-intelligence not yet available.** Falls back to manual grounding. Notes confidence level per major architectural claim. Reviewer pays extra attention to claims marked as inferred.
- **Reviewer verdict `changes_requested` cannot be addressed by orchestrator's auto-remediation rules.** Surface to the human as a blocker requiring direction. Don't grind through endless revision rounds without surfacing.
- **Drift detected since PRD approval.** Reconciliation flags codebase changes in PRD-referenced paths. Lean drift worker dispatched (`telec sessions run --command /next-drift-analyze`); orchestrator integrates findings; if substantive, re-engages PRD approval gate before continuing architecture.
- **Architecture would require a flavor that doesn't exist.** This is a blocking finding, not a license to hack a one-off. Orchestrator surfaces the gap and either: (a) recommends the user defer this work until the flavor is built; (b) recommends splitting off the flavor-build as its own todo first; (c) proceeds with explicit human approval to hack a one-off, with the hack documented as tech debt.

## See Also

- ~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- ~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/intake.md
