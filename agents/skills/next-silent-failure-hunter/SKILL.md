---
name: next-silent-failure-hunter
description: Identify silent failures, inadequate error handling, and inappropriate fallback behavior. Use when reviewing code with error handling, catch blocks, or fallback logic.
---

# Silent Failure Hunter

## Required reads

- @~/.teleclaude/docs/software-development/procedure/silent-failure-audit.md

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

Follow the silent failure audit procedure. Full evaluation criteria and hidden-failure patterns are in the required reads above.
