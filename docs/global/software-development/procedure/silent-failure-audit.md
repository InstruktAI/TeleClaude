---
description: 'Audit error handling paths to identify silent failures, inadequate logging, and inappropriate fallback behavior.'
id: 'software-development/procedure/silent-failure-audit'
scope: 'domain'
type: 'procedure'
---

# Silent Failure Audit — Procedure

## Goal

Eliminate silent failures and weak recovery paths by systematically auditing error handling code. Surface issues that hide errors, mislead users, or swallow exceptions without recovery.

## Preconditions

- Files containing error handling, fallback logic, or retries are available.
- Project logging patterns and error identifier conventions are known or discoverable.

## Steps

1. **Locate error handling paths** — Find all try/catch blocks, error callbacks, fallback values, optional chaining, and retry logic in scope.
2. **Evaluate each handler** for:
   - **Logging quality** — Is context (request ID, user, operation) captured? Is the log level appropriate?
   - **User feedback** — Is the error communicated clearly and actionably, or silently swallowed?
   - **Catch specificity** — Is the catch too broad (catches `Exception`, `Error`, `*`)? Broad catches hide unexpected failures.
   - **Fallback behavior** — Does the fallback silently degrade in a way that could mislead? Is the degraded state observable?
   - **Propagation correctness** — Is the error re-thrown, transformed, or swallowed when it should propagate?
3. **Flag hidden-failure patterns**:
   - Empty catch blocks
   - Log-and-continue without surfacing to the caller
   - Silent default values that mask errors (e.g., `catch { return [] }`)
   - Optional chaining that obscures null/undefined propagation
   - Retry loops with no failure escalation path
4. **Report each issue** with: location (file:line), severity, description, and what errors it could mask.

## Outputs

- Issue list with severity, location, and remediation guidance.
- Prioritized by blast radius: issues that can silently corrupt state or hide user-facing failures rank highest.

## Recovery

- If scope is too large for a single pass, prioritize by blast radius: focus on public API boundaries, data mutation paths, and user-facing flows first.
- If logging patterns are unclear, inspect existing error sites for precedent before reporting gaps.
