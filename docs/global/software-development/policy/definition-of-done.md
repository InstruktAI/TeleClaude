---
description:
  Baseline quality gates defining when work is truly complete. Functionality,
  quality, testing, security, documentation.
id: software-development/policy/definition-of-done
scope: domain
type: policy
---

# Definition Of Done — Policy

## Rule

- @docs/software-development/policy/code-quality
- @docs/software-development/policy/testing
- @docs/software-development/policy/commits

@~/.teleclaude/docs/software-development/standards/code-quality.md
@~/.teleclaude/docs/software-development/standards/testing.md
@~/.teleclaude/docs/software-development/standards/commits.md

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
- [ ] Contract violations fail fast

### 3. Testing

- [ ] Pre-commit hooks pass
- [ ] All tests pass
- [ ] New tests added for new functionality
- [ ] Edge cases have test coverage
- [ ] Tests are deterministic (no flaky tests)
- [ ] Test names are descriptive
- [ ] Tests verify behavior, not implementation

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

### 7. Commit Hygiene

- [ ] Change is atomic and complete
- [ ] Commit message follows format
- [ ] Attribution footer present
- [ ] Pre-commit hooks verified
- [ ] No `--no-verify` used

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

### Before Finalize

- [ ] Changes merged/delivered
- [ ] State updated
- [ ] Delivery logged in todos/delivered.md
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

Work is complete when:

1. All baseline quality gates pass
2. Code is production-ready
3. No known issues remain
4. You would be proud to maintain this code yourself
5. Another developer can understand and modify it

- TBD.

- TBD.

- TBD.

- TBD.

## Rationale

- TBD.

## Scope

- TBD.

## Enforcement

- TBD.

## Exceptions

- TBD.
