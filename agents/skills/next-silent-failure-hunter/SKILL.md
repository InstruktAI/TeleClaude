---
name: next-silent-failure-hunter
description: Identify silent failures, inadequate error handling, and inappropriate fallback behavior. Use when reviewing code with error handling, catch blocks, or fallback logic.
---

# Silent Failure Hunter

## Purpose

Audit error handling to eliminate silent failures and weak recovery paths.

## Scope

- Review try/catch blocks, error handlers, fallbacks, and optional chaining.
- Prioritize issues that hide errors or mislead users.

## Inputs

- Files containing error handling, fallback logic, or retries
- Project logging patterns and error identifiers

## Outputs

- Issues with severity, location, and remediation guidance

## Procedure

- Locate all error handling paths (try/catch, error callbacks, fallbacks).
- For each handler, evaluate:
  - Logging quality and context
  - User feedback clarity and actionability
  - Catch specificity (avoid broad catches)
  - Fallback behavior (no hidden failures)
  - Propagation correctness (don’t swallow errors)
- Flag hidden-failure patterns: empty catches, log-and-continue, silent defaults, optional chaining that masks errors.
- Report each issue with location, severity, description, and hidden errors it could mask.
