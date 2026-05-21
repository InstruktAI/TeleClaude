---
description: 'Baseline quality gates defining when work is truly complete. Functionality, quality, testing, security, documentation.'
id: 'software-development/policy/definition-of-done'
scope: 'domain'
type: 'policy'
visibility: 'public'
---

# Definition Of Done — Policy

## Rules

Work is not done when code is written. Work is done when it meets all quality gates and is ready for production.

Before considering ANY work complete, verify ALL criteria are met:

### 1. Functionality

- [ ] All requirements implemented
- [ ] Code works as specified
- [ ] Edge cases handled
- [ ] Error paths tested
- [ ] No debug/temp code remains

### 2. Code Quality

- [ ] Follows project patterns and conventions
- [ ] Types explicit and complete
- [ ] No new abstractions beyond requirements
- [ ] Functions are pure where appropriate
- [ ] Dependencies passed explicitly
- [ ] No code duplication
- [ ] No unjustified fallback paths (each fallback has a code comment explaining why UX requires it)
- [ ] Contract violations fail fast

### 3. Testing

- [ ] Pre-commit hooks pass
- [ ] All tests pass
- [ ] Expected-failure markers removed for all in-scope test specifications
- [ ] Test specs delivered for all new behavioral requirements
- [ ] Bug fixes include reproduction test
- [ ] No test assertions weakened or deleted from spec-delivered tests
- [ ] New tests added for new functionality
- [ ] Edge cases have test coverage
- [ ] Tests are deterministic (no flaky tests)
- [ ] Test names are descriptive
- [ ] Tests verify behavior, not implementation
- [ ] Browser-based frontend or web UI changes pass a Playwright smoke test

### 4. Linting & Type Checking

- [ ] No lint violations
- [ ] No type errors
- [ ] No unused imports
- [ ] No unused variables
- [ ] All imports at module top level
- [ ] Type annotations complete

### 5. Security

- [ ] No secrets committed
- [ ] No sensitive data in logs
- [ ] Input validation at boundaries
- [ ] No injection vulnerabilities
- [ ] Authorization checks present
- [ ] Error messages don't leak info

### 6. Documentation

- [ ] Comments accurate (not stale)
- [ ] Complex logic explained
- [ ] API contracts documented
- [ ] Breaking changes noted
- [ ] No commented-out code
- [ ] README and docs updated to reflect current behavior
- [ ] User-facing interface documentation updated for new/changed commands
- [ ] If new configuration surface introduced, relevant documentation and tooling updated

### 7. Commit Hygiene

- [ ] Change is atomic and complete
- [ ] Commit message follows format
- [ ] Attribution footer present
- [ ] Pre-commit hooks verified

### 8. Observability

- [ ] Logging at key boundaries
- [ ] Appropriate log levels used
- [ ] Context included in log messages
- [ ] Error paths logged

### After Build

- [ ] Implementation matches plan
- [ ] All task checkboxes completed
- [ ] Code committed
- [ ] No TODOs or FIXMEs without tickets

### After Review

- [ ] All review findings addressed
- [ ] Verdict is APPROVE
- [ ] No critical issues remain
- [ ] Tests still pass
- [ ] Browser-based frontend or web UI changes are re-verified during review, or a verification gap is recorded as a finding

### Before Finalize

- [ ] Changes merged/delivered
- [ ] State updated
- [ ] Delivery logged in todos.db
- [ ] Clean working directory

Work is NOT done if ANY of these are true:

- ❌ "Tests failing but I'll fix them later"
- ❌ "Lint errors but they're minor"
- ❌ "Works on my machine"
- ❌ "I'll add tests in a follow-up"
- ❌ "Missing edge case but it's unlikely"
- ❌ "Hardcoded for now, will parameterize later"
- ❌ "Bypassed hooks to commit faster"
- ❌ "Commented out broken code"

## Rationale

- A consistent DoD prevents “almost done” work from leaking into production.
- Explicit gates reduce regressions and hidden operational costs.

## Scope

- Applies to all features, bug fixes, and doc changes merged to main.

## Enforcement

- CI and reviewers must confirm DoD checks before approval.
- Work items are not marked delivered until DoD is satisfied.

## Exceptions

- Emergency hotfixes may defer non-critical DoD items with explicit follow-up tickets.
