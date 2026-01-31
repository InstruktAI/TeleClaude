---
name: next-test-analyzer
description: Review test coverage quality and completeness. Use after creating a PR or adding new functionality to ensure tests adequately cover new code and edge cases.
---

# Test Analyzer

## Purpose

Assess test coverage quality and identify critical gaps without chasing 100% coverage.

## Scope

- Focus on behavioral coverage, critical paths, and edge cases.
- Avoid suggesting tests for trivial code unless it contains logic.

## Inputs

- `~/.teleclaude/docs/development/testing-directives.md`
- Tests for changed modules
- Source code under review
- Existing test patterns

## Outputs

- Summary of coverage quality
- Critical gaps, important improvements, and test quality issues
- Positive observations (where useful)

## Procedure

- Map new/changed functionality to existing tests.
- Identify missing coverage for error paths, boundaries, and business logic branches.
- Evaluate test quality (behavior vs implementation, resilience to refactors).
- Rate recommendations by criticality (1–10) and explain the regression they prevent.
- Report findings in a structured list with clear priorities.
