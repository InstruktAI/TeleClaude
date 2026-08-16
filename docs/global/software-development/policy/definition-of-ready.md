---
description: 'Definition of Ready gates for work items before they enter implementation. Establishes required inputs, scope clarity, and verification readiness.'
visibility: 'public'
---

# Definition Of Ready — Policy

## Rules

A todo is **Ready** only when all gates below are satisfied. If any gate fails,
the item is blocked until it is clarified, split, or deferred.

Gates (all required):

1. **Intent & success**

- The authorized outcome horizon is explicit.
- The target is richer than the input where situation-specific domain
  intelligence earns that enrichment, without converting advice into human
  intent.
- Consequential inclusions and exclusions explain why they belong here,
  resting on inspectable premises or named assumptions.
- Success criteria describe observable outcomes rather than mechanisms or
  concrete proof.
- Product intent has passed independent preparation review before human
  approval. For no-PRD work, plan review applies the same contract to the
  plan's _Intent & scope_.

2. **Scope & size**
   - The work is one coherent, bounded delivery. Execution may span builder
     sessions only when the implementation plan provides durable task
     boundaries, completed-work evidence, and an unambiguous resumption point,
     so continuation requires no rediscovery.
   - Cross-cutting changes are called out explicitly and justified.
   - Every behavior, invariant, state transition, validation rule, and
     vocabulary decision has one named bounded-context owner. Cross-context
     work is partitioned into owner-local changes joined by explicit contracts;
     todo coherence never creates shared ownership.
   - Multiple phases remain tasks in one todo when they share an indivisible
     cutover or observable outcome. They become dependent todos only when the
     resulting pieces pass the coherence test below.

   **Splitting heuristics — read the code before deciding:**
   - **Ground first.** Open the actual source files listed in the input before
     deciding to split. Estimate change volume and complexity, not files or
     plan tasks counted. A 3-line edit across 15 files is one bounded delivery.
     Never split based on the input description alone.
   - **Coherence test.** One behavior = one todo. A model change flowing through
     its consumers (DTOs, renderers, CLI flags, tests) is one behavior, not four.
     Only split when the pieces are independently shippable AND independently
     valuable. If splitting creates a half-working codebase, don't split; give
     the coherent delivery durable execution boundaries instead.
   - **Detail inverts complexity.** A detailed input with exact file paths, line
     numbers, and before/after code means the approach is fully known. Treat
     detail as reducing the case for splitting — the discovery is done, what
     remains is mechanical execution.
   - **Coordination cost.** Splitting creates inter-todo dependencies, state
     management, review overhead, and sequencing complexity. If the coordination
     cost exceeds the session-size benefit, don't split.

3. **Verification**

- Observable verification criteria exist for every behavioral outcome.
- Every behavioral outcome has an observation-map entry in the plan wiring it
  to the runtime evidence that proves it
  (`software-development/spec/observation-map`), covering both the use cases
  the work delivers and the unchanged use cases its blast radius places at
  risk.
- The implementation plan names the concrete proof that applies under the
  project's verification contract: executable tests, live-system behavior,
  browser evidence, or another sanctioned source.
- Edge cases and error paths are addressed or explicitly deferred with a
  meaningful trigger.
- Definition of Done applies and is not contradicted by the task.

4. **Approach known**

- Current patterns and credible intended state have been assessed against
  the approved target.
- Reuse is the default when it serves the target; any adaptation,
  replacement, retirement, or deliberate divergence has a grounded reason.
- Unknowns are small; if not, an evidence-gathering todo exists first.
- No architectural decision that could change the plan remains unresolved.
- Every plan task names both its bounded-context owner and its architectural
  layer inside that context. Every crossing names the published command,
  query, event, or type through which the consumer depends on the owner.

5. **Research complete (when applicable)**
   - Third-party tools, libraries, or integrations have been researched.
   - Research findings are indexed as third-party docs (global or project).
   - Sources are authoritative and documented in the findings.
   - If no third-party dependencies exist, this gate is automatically satisfied.
   - Triggered when the change introduces or modifies third-party tooling/integrations.
6. **Security awareness (when applicable)**
   - If the change introduces or modifies API endpoints, authentication or
     authorization boundaries, data handling, user input paths, or credential
     management: requirements must identify security implications and the
     implementation plan must include specific tasks to address them.
   - If the change has no security surface, this gate is automatically satisfied.
   - Triggered when the change touches trust boundaries or data flows.
7. **Performance sensitivity (when applicable)**
   - If the change touches hot paths, large dataset operations, latency-critical
     flows, or resource-intensive operations: requirements must note the
     performance constraints and the implementation plan must address them.
   - If the change is not performance-sensitive, this gate is automatically
     satisfied.
   - Triggered when the change affects throughput, latency, or resource
     consumption.
8. **Dependencies & preconditions**
   - Prerequisite tasks are listed and blocked if needed.
   - Required configs, access, and environments are known.
   - Required external systems are reachable or stubbed.
9. **Integration safety**
   - The change can be merged incrementally without destabilizing main.
   - Entry/exit points are explicit; rollback or containment exists if risky.
10. **Tooling impact (only if applicable)**
    - If the work changes tooling or scaffolding, the relevant scaffolding
      procedure is updated and verified once.
    - If tooling is unchanged, this gate is automatically satisfied.

Decision:

- **Ready**: proceed to the work phase (build).
- **Not Ready**: block the item until remediation is complete.

Remediation playbook:

- Horizon or product judgment unclear → retain the unresolved human-owned
  decision and return to intent shaping.
- Generic or unsupported scope → replace recital with a situation-specific
  reason, inspectable premise, or named assumption.
- Valuable outcome omitted → re-run the open shaping questions and revise the
  current slice.
- Too large for one uninterrupted execution context → establish durable task
  boundaries and resumption evidence first; split only when the resulting
  todos are independently shippable and independently valuable.
- Unknown approach → gather authoritative solution evidence before planning.
- Unresolved or shared ownership → resolve the context boundary and contracts
  before planning implementation; current placement, hosting, or caller
  proximity is not a default.
- Missing verification → establish observable outcomes, then make the plan
  name concrete project-sanctioned proof.
- Security, performance, or tooling gaps → address them where this situation
  triggers them; do not add work merely to satisfy a catalogue.

## Rationale

- Readiness gates prevent ambiguous, oversized, or unverifiable work from
  entering the build pipeline.
- Clear readiness reduces rework, churn, and review failures.

## Scope

- Applies to all todos before entering the build phase.

## Enforcement

- The prepare phase and its independent review gates produce artifacts that
  satisfy these readiness properties.

- Orchestrators must not dispatch build work for items that haven't completed
  prepare.

## Exceptions

- Emergency hotfixes may bypass gates with explicit risk acceptance and follow-up.
