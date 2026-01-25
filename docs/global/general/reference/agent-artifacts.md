---
id: general/reference/agent-artifacts
type: reference
scope: global
description: Minimal schema used for agent artifacts (commands and skills).
---

# Agent Artifacts — Reference

## What it is

Defines the minimal, shared schema for agent artifacts. Commands and skills use the
same frontmatter pattern and freeform bodies; the intent differs by scope, not schema.

## Canonical fields

- **Frontmatter (shared)**:
  - `name` (skills) or title in body (commands)
  - `description`
  - `argument-hint` (commands, optional)
- **Body**:
  - Freeform Markdown instructions.
  - Required reads as inline `@` references when needed.

## Allowed values

- `description`: short, imperative summary.
- `argument-hint`: optional string for CLI argument hints (commands).

## Known caveats

- Commands and skills share the same minimal schema; do not invent extra frontmatter fields.
- Scope is conveyed by location:
  - **Global scope**: `TeleClaude/agents/commands/*.md`, `TeleClaude/agents/skills/*/SKILL.md`
  - **Project scope**: `<project>/.agents/commands/*.md`, `<project>/.agents/skills/*/SKILL.md`
- Keep prompts concise to avoid bloated agent context.
