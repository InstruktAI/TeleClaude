# Agent Transpilation (Local)

Required reads

@~/.teleclaude/docs/baseline/reference/agent-artifacts.md

## What it is

Local rules for converting master artifacts into runtime-specific formats.

## Canonical sources

- `AGENTS.master.md`
- `commands/*.md`
- `skills/*/SKILL.md`

## Runtime mappings

- Claude: preserves frontmatter and uses slash commands.
- Codex: uses prompt files and subject-style arguments.
- Gemini: uses TOML with argument substitution.

## Placeholders

- `{AGENT_PREFIX}` is replaced with runtime-specific prefixes.

## Outputs

- `dist/claude/*`
- `dist/codex/*`
- `dist/gemini/*`
