---
id: general/reference/agent-artifacts
type: reference
scope: global
description: Minimal schema used for agent artifacts (commands and skills).
---

# Agent Artifacts — Reference

## What it is

Defines the minimal, shared schema for agent artifacts in this repo. Commands and skills use the same frontmatter pattern and freeform bodies; the intent differs by file location, not by schema.

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
- Use the file location to convey intent:
  - `agents/commands/*.md` for commands.
  - `agents/skills/*/SKILL.md` for skills.
- Keep prompts concise to avoid bloated agent context.
