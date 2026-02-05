---
description: Definition of Ready gates for work items before they enter implementation.
  Establishes required inputs, scope clarity, and verification readiness.
id: software-development/policy/definition-of-ready
scope: domain
type: policy
---

# Definition Of Ready — Policy

## Rules

A todo is **Ready** only when all gates below are satisfied. If any gate fails,
the item is blocked until it is clarified, split, or deferred.

Gates (all required):

1. **Intent & success**
   - The problem statement and intended outcome are explicit.
   - The “what” and “why” are captured in `input.md` or `requirements.md`.
   - Success criteria are concrete and testable (not “works” or “better”).
2. **Scope & size**
   - The work is atomic and fits a single AI session without context exhaustion.
   - Cross-cutting changes are called out explicitly and justified.
   - If it requires multiple phases, it is split into dependent todos.
3. **Verification**
   - There is a clear way to verify completion (tests, logs, or observable behavior).
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
6. **Dependencies & preconditions**
   - Prerequisite tasks are listed and blocked via `dependencies.json` if needed.
   - Required configs, access, and environments are known.
   - Required external systems are reachable or stubbed.
7. **Integration safety**
   - The change can be merged incrementally without destabilizing main.
   - Entry/exit points are explicit; rollback or containment exists if risky.
8. **Tooling impact (only if applicable)**
   - If the work changes tooling or scaffolding, the relevant scaffolding procedure is updated and verified once.
   - If tooling is unchanged, this gate is automatically satisfied.

Decision:

- **Ready**: proceed to implementation planning and scheduling.
- **Not Ready**: block the item until remediation is complete.

Remediation playbook:

- Too large → split into smaller todos with dependencies.
- Unclear requirements → clarify with the requester before planning.
- Unknown approach → create a research todo or spike first.
- Missing research → document third-party findings before planning.
- Missing verification → define tests or observable checks.
- Tooling changes → update scaffolding procedures and validate once.

## Rationale

- Readiness gates prevent ambiguous, oversized, or unverifiable work from
  entering the build pipeline.
- Clear readiness reduces rework, churn, and review failures.

## Scope

- Applies to all todos before entering the build phase.

## Enforcement

- Architects must assess readiness before marking items ready in the roadmap.
- Orchestrators must not dispatch build work for items that fail readiness.

## Exceptions

- Emergency hotfixes may bypass gates with explicit risk acceptance and follow-up.
