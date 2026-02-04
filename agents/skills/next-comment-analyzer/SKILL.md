---
name: next-comment-analyzer
description: Analyze code comments for accuracy, completeness, and long-term maintainability. Use after adding documentation, before finalizing PRs with comment changes, or when reviewing existing comments for technical debt.
---

# Comment Analyzer

## Required reads

@~/.teleclaude/docs/software-development/policy/code-quality.md

## Purpose

Evaluate comments for accuracy, completeness, and long-term value.

## Scope

- Treat comments skeptically; prefer accuracy over preservation.
- Focus on comments that explain behavior, rationale, or constraints.

## Inputs

- Code referenced by the comments
- Related context in the same module or feature
- Existing documentation patterns in the project

## Outputs

- Summary of findings
- Lists of critical issues, improvement opportunities, and removals with file:line and suggestions

## Procedure

- Verify factual accuracy against actual code behavior and signatures.
- Assess completeness: preconditions, side effects, error cases, and rationale.
- Evaluate long-term value: avoid comments that restate code or become stale.
- Identify misleading elements: ambiguity, outdated references, invalid examples, stale TODOs.
- Provide specific rewrite or removal suggestions.
