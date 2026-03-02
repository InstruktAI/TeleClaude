---
name: skill-creator
description: Create new skills that follow the agent-artifact schema. Use when creating a new skill or updating an existing skill.
---

# Skill Creator

## Required reads

- @~/.teleclaude/docs/general/procedure/skill-authoring.md

## Purpose

Scaffold and author new skills that follow the agent-artifact schema, using doc snippets as the knowledge layer and optional scripts for deterministic tooling.

## Scope

- Creating new skills in `agents/skills/`.
- Updating existing skills to conform to the schema.
- Skills are thin wrappers around doc snippets — this skill enforces that pattern.

## Inputs

- Intent: what capability the new skill provides.
- The doc snippet(s) the skill will wrap (or enough context to create them first).

## Outputs

- A skill directory in `agents/skills/{skill-name}/` with SKILL.md and optional scripts.
- Compiled and deployed via `telec sync`.

## Procedure

Follow the skill authoring procedure in the required reads above. Use `scripts/init_skill.py` to scaffold the directory:

```bash
scripts/init_skill.py <skill-name> [--path agents/skills]
```

The script creates a SKILL.md with the correct schema sections and TODO placeholders. Replace the placeholders, point Required reads at the relevant doc snippet, and run `telec sync`.
