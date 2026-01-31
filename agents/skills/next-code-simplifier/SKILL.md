---
name: next-code-simplifier
description: Simplify code for clarity, consistency, and maintainability while preserving all functionality. Use after completing a coding task or after passing code review to polish the implementation.
---

# Code Simplifier

## Purpose

Refine code for clarity and maintainability without changing behavior.

## Scope

- Focus on code modified in the current session unless explicitly asked to expand.
- Prefer clarity over brevity; avoid overly clever refactors.

## Inputs

- Project standards (`AGENTS.md` or `CLAUDE.md`)
- `~/.teleclaude/docs/development/coding-directives.md`
- Relevant code context and patterns

## Outputs

- Simplifications grouped by file, with location, change, and rationale

## Procedure

- Preserve behavior exactly; do not change outputs or features.
- Apply project coding standards (imports, types, naming, error handling, patterns).
- Reduce complexity: remove redundancy, simplify nesting, improve naming.
- Avoid nested ternaries; prefer clear conditional structures.
- Avoid over-simplification that harms clarity or structure.
- For each change, report: location, issue, simplified version, rationale.
