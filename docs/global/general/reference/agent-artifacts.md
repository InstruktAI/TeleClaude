---
id: general/reference/agent-artifacts
type: reference
scope: global
description: Minimal schema used for agent artifacts (commands and skills).
---

# Agent Artifacts — Reference

## What it is

Defines the normalized artifact formats we author and how they map to each supported
agent runtime. This doc is the concrete reference for what exists, what is emitted,
and where those outputs land.

## Canonical fields

- **Commands**:
  - Frontmatter: `description`, optional `argument-hint`
  - Body: freeform instructions
- **Skills**:
  - Frontmatter: `name`, `description`
  - Body: freeform instructions
- **Agents**:
  - Frontmatter: `name`, `description`, optional tool and permission fields
  - Body: agent/system prompt content
- **Hooks**:
  - Frontmatter and body follow the target runtime’s hook schema

## Allowed values

- `description`: short, imperative summary.
- `argument-hint`: optional string for CLI argument hints (commands).
- `name`: identifier used for skill/agent lookup; must match the skill folder name.

## Known caveats

- Commands and skills share the same minimal schema; do not invent extra frontmatter fields.
- Scope is conveyed by location:
  - **Global scope**: `TeleClaude/agents/commands/*.md`, `TeleClaude/agents/skills/*/SKILL.md`
  - **Project scope**: `<project>/.agents/commands/*.md`, `<project>/.agents/skills/*/SKILL.md`
- Keep prompts concise to avoid bloated agent context.
- Required reads in source docs are **inlined** in generated outputs; `@` references
  are transformed into inline content and do not appear in emitted files.

### Runtime support matrix

- **Claude Code**
  - Commands, Skills, Agents, Hooks
  - Outputs: `~/.claude/` (global) and `.claude/` (project)
- **Codex CLI**
  - Commands, Skills
  - No Hooks, no Agents
  - Outputs: `~/.codex/` (global) and `.codex/` (project)
- **Gemini CLI**
  - Commands, Skills, Hooks
  - No Agents
  - Outputs: `~/.gemini/` (global) and `.gemini/` (project)
