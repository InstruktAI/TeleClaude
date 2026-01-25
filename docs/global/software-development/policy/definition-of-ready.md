---
description:
  Definition of Ready gates for work items before they enter implementation.
  Establishes required inputs, scope clarity, and verification readiness.
id: software-development/policy/definition-of-ready
scope: domain
type: policy
---

# Definition Of Ready — Policy

## Rule

A todo is **Ready** only when all gates below are satisfied. If any gate fails,
the item must be clarified, split, or deferred before it enters implementation.

### 1) Clear Intent

- Problem statement and intended outcome are explicit.
- "What" and "why" are documented (requirements or input.md).
- Success criteria are concrete and unambiguous.

### 2) Bounded Scope

- Work is atomic and fits a single AI session without context exhaustion.
- No cross-cutting changes unless explicitly called out.
- Dependency graph is known; prerequisites are listed or satisfied.

### 3) Verifiable Outcomes

- Acceptance criteria can be checked (tests, logs, or observable behavior).
- There is a clear definition of done for the item.
- Edge cases and error paths are identified or explicitly deferred.

### 4) Known Approach

- The technical path is established or the pattern exists in the codebase.
- Unknowns are identified; if substantial, create a research todo first.
- No architectural decisions remain unresolved.

### 5) Safe Integration

- The change can be merged incrementally without destabilizing main.
- Entry and exit points are explicit.
- Rollback or containment strategy is clear if behavior is risky.

### 6) Tooling Impact (Gate Only If Relevant)

- If the work changes tooling or scaffolding, update the relevant scaffolding
  procedure and verify the tooling baseline once.
- Otherwise, tooling setup is not a per-todo requirement.

## Outcomes

- **Ready**: proceed to implementation planning and scheduling.
- **Not Ready**: clarify, split, or create prerequisite tasks.

## Remediation

- Too large → split into smaller todos with dependencies.
- Unclear requirements → clarify with the requester before planning.
- Unknown approach → create a research todo or spike first.
- Tooling changes → update scaffolding procedures and validate once.

## Rationale

- Readiness gates prevent ambiguous, oversized, or unverifiable work from
  entering the build pipeline.
- Clear readiness reduces rework, churn, and review failures.

## Scope

- Applies to all todos before entering the build phase.

## Enforcement

- Architects must assess readiness before marking items ready in the roadmap.
- Orchestrators should not dispatch build work for items that fail readiness.

## Exceptions

- Emergency hotfixes may bypass gates with explicit risk acceptance and follow-up.
