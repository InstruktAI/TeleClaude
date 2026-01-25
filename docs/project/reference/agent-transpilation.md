---
id: reference/agent-transpilation
type: reference
scope: global
description: Rules for transpiling master artifacts into runtime-specific formats.
---

# Agent Transpilation — Reference

## What it is

Local rules for converting master artifacts into runtime-specific formats.

## Canonical fields

- Inputs: `AGENTS.master.md`, `commands/*.md`, `skills/*/SKILL.md`.
- Outputs: `dist/claude/*`, `dist/codex/*`, `dist/gemini/*`.

## Allowed values

- Claude: preserves frontmatter and uses slash commands.
- Codex: uses prompt files and subject-style arguments.
- Gemini: uses TOML with argument substitution.

## Known caveats

- `{AGENT_PREFIX}` is replaced with runtime-specific prefixes.
- Generated artifacts should not be edited directly.
