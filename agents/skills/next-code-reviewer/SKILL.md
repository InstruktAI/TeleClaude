---
name: next-code-reviewer
description: Review code for adherence to project guidelines, style guides, and best practices. Use after writing or modifying code, before committing changes or creating pull requests.
---

This skill reviews code against project guidelines with high precision to minimize false positives.

## Context to Gather

Before reviewing, read:

- `AGENTS.md` or `CLAUDE.md` - Project-specific guidelines
- `~/.teleclaude/docs/development/coding-directives.md` - Coding standards
- Related source files to understand patterns

## Review Scope

By default, review unstaged changes from `git diff`. The caller may specify different files or scope.

## Core Review Responsibilities

**Project Guidelines Compliance**: Verify adherence to explicit project rules including import patterns, framework conventions, language-specific style, function declarations, error handling, logging, testing practices, platform compatibility, and naming conventions.

**Bug Detection**: Identify actual bugs that will impact functionality - logic errors, null/undefined handling, race conditions, memory leaks, security vulnerabilities, and performance problems.

**Code Quality**: Evaluate significant issues like code duplication, missing critical error handling, accessibility problems, and inadequate test coverage.

## Issue Confidence Scoring

Rate each issue from 0-100:

- **0-25**: Likely false positive or pre-existing issue
- **26-50**: Minor nitpick not explicitly in guidelines
- **51-75**: Valid but low-impact issue
- **76-90**: Important issue requiring attention
- **91-100**: Critical bug or explicit guideline violation

**Only report issues with confidence >= 80**

## Output Format

Start by listing what you're reviewing. For each high-confidence issue provide:

- Clear description and confidence score
- File path and line number
- Specific guideline rule or bug explanation
- Concrete fix suggestion

Group issues by severity (Critical: 90-100, Important: 80-89).

If no high-confidence issues exist, confirm the code meets standards with a brief summary.

Be thorough but filter aggressively - quality over quantity. Focus on issues that truly matter.
