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
  - Body: normalized command schema (see below)
- **Skills**:
  - Frontmatter: `name`, `description`
  - Body: normalized skill schema (see below)
- **Agents**:
  - Frontmatter: `name`, `description`, optional tool and permission fields
  - Body: normalized agent schema (see below)
- **Hooks**:
  - Frontmatter and body follow the target runtime’s hook schema

## Allowed values

- `description`: short, imperative summary.
- `argument-hint`: optional string for CLI argument hints (commands).
- `name`: identifier used for skill/agent lookup; must match the skill folder name.

No free text is allowed between the H1 title and the first schema section.
If required reads are needed, place a `## Required reads` section immediately after
the H1 title, ordered from general to concrete: concept → principle → policy → role
→ procedure → reference. After required reads, use the schema below for each artifact type.

### Commands

1. `# <Command Name>`
2. `## Required reads` (only if needed)
3. Activation line: `You are now the <Role>.`
4. `## Purpose`
5. `## Inputs`
6. `## Outputs`
7. `## Steps`
8. `## Examples` (optional)

### Skills

1. `# <Skill Name>`
2. `## Required reads` (only if needed)
3. `## Purpose`
4. `## Scope`
5. `## Inputs`
6. `## Outputs`
7. `## Procedure`
8. `## Examples` (optional)

### Agents

1. `# <Agent Name>`
2. `## Required reads` (only if needed)
3. Activation line: `You are now the <Role>.`
4. `## Purpose`
5. `## Scope`
6. `## Inputs`
7. `## Outputs`
8. `## Procedure`
9. `## Examples` (optional)

### Optional sections (all artifacts)

- `## Limitations` — only when real constraints exist.
- `## Examples` — only when concrete usage is needed.
- `## See also` — soft references only; no inline `@` references.

Avoid generic `Notes` sections. If content does not fit the mandatory sections
or the optional sections above, it should not be included.

## Known caveats

- Commands and skills share the same minimal frontmatter; do not invent extra fields.
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
