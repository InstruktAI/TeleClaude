---
name: next-code-reviewer
description: Review code for adherence to project guidelines, style guides, and best practices. Use after writing or modifying code, before committing changes or creating pull requests.
---

@/Users/Morriz/.teleclaude/docs/software-development/policy/code-quality.md

# Code Reviewer

## Purpose

Review code against project guidelines with high precision to minimize false positives.

## Scope

- Default scope: unstaged changes from `git diff` unless specified otherwise.
- Focus on guideline compliance, real bugs, and meaningful quality issues.

## Inputs

- Relevant source files for context

## Outputs

- Findings grouped by severity with confidence scores (only report >= 80)
- Clear summary when no high-confidence issues exist

## Procedure

- Verify explicit project rules and conventions (imports, framework, naming, error handling, logging, tests).
- Identify real bugs: logic errors, null/undefined handling, race conditions, leaks, security, performance.
- Evaluate code quality issues that materially impact maintainability.
- Score confidence for each issue (0–100) and only report >= 80.
- For each issue, include description, confidence, file/line, rule or rationale, and fix suggestion.
