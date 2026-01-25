# Claude Code Agents (Subagents)

## Overview

Claude Code supports subagents defined as Markdown files with YAML frontmatter. The body of
the file becomes the subagent's system prompt. Subagents can be managed with the `/agents`
command.

## Locations and precedence

Subagent definitions can come from:

- `--agents` CLI JSON (highest priority)
- `.claude/agents/` in the project
- `~/.claude/agents/` for personal agents
- `<plugin>/agents/` for plugin agents

## Common frontmatter fields

- `name`, `description`
- `tools` / `disallowedTools`
- `model`, `permissionMode`
- `skills`, `hooks`

## Sources

- https://code.claude.com/docs/en/sub-agents
