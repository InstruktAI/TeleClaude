---
description: 'Definition of Ready gates for work items before they enter implementation. Establishes required inputs, scope clarity, and verification readiness.'
id: 'software-development/policy/definition-of-ready'
scope: 'domain'
type: 'policy'
visibility: 'public'
---

# Definition Of Ready — Policy

## Rules

A todo is **Ready** only when all gates below are satisfied. If any gate fails,
the item is blocked until it is clarified, split, or deferred.

Gates (all required):

1. **Intent & success**
   - The problem statement and intended outcome are explicit.
   - The “what” and “why” are captured in requirements.
   - Success criteria are concrete and testable (not “works” or “better”).
2. **Scope & size**
   - The work is atomic and fits a single session without context exhaustion.
   - Cross-cutting changes are called out explicitly and justified.
   - If it requires multiple phases, it is split into dependent todos.

   **Splitting heuristics — read the code before deciding:**
   - **Ground first.** Open the actual source files listed in the input before
     deciding to split. Estimate lines of change, not files touched. A 3-line
     edit across 15 files is one session. Never split based on the input
     description alone.
   - **Coherence test.** One behavior = one todo. A model change flowing through
     its consumers (DTOs, renderers, CLI flags, tests) is one behavior, not four.
     Only split when the pieces are independently shippable AND independently
     valuable. If splitting creates a half-working codebase, don't split.
   - **Detail inverts complexity.** A detailed input with exact file paths, line
     numbers, and before/after code means the approach is fully known. Treat
     detail as reducing the case for splitting — the discovery is done, what
     remains is mechanical execution.
   - **Coordination cost.** Splitting creates inter-todo dependencies, state
     management, review overhead, and sequencing complexity. If the coordination
     cost exceeds the session-size benefit, don't split.

3. **Verification**
   - Feature-spec acceptance scenarios or equivalent observable verification criteria exist for all behavioral requirements.
   - There is a clear way to verify completion through executable tests or
     observable system behavior. Logs may support manual diagnosis, but they
     are not default automated assertion targets for feature behavior.
   - Edge cases and error paths are identified or explicitly deferred.
   - Definition of Done applies and is not contradicted by the task.
4. **Approach known**
   - The technical path is known or a proven pattern exists in the codebase.
   - Unknowns are small; if not, a research/spike todo exists first.
   - No architectural decisions remain unresolved.
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

- Too large → split into smaller todos with dependencies.
- Unclear requirements → clarify with the requester before planning.
- Unknown approach → create a research todo or spike first.
- Missing research → document third-party findings before planning.
- Missing verification → define tests or observable checks.
- Security gaps → surface implications in requirements and plan.
- Performance gaps → note constraints in requirements and plan.
- Tooling changes → update scaffolding procedures and validate once.

## Rationale

- Readiness gates prevent ambiguous, oversized, or unverifiable work from
  entering the build pipeline.
- Clear readiness reduces rework, churn, and review failures.

## Scope

- Applies to all todos before entering the build phase.

## Enforcement

- The prepare phase produces artifacts that satisfy these gates. The pair's
  process during prepare is the primary mechanism for ensuring readiness.
- Orchestrators must not dispatch build work for items that haven't completed
  prepare.

## Exceptions

- Emergency hotfixes may bypass gates with explicit risk acceptance and follow-up.
