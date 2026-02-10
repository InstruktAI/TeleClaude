# Claude Code Commands

## Overview

Claude Code exposes built-in slash commands and supports custom slash commands. Custom
commands are created as Markdown files in `.claude/commands/` or via skills in
`.claude/skills/`, and they are invoked as `/command-name`.

## Custom command locations

- `.claude/commands/*.md` (project)
- `~/.claude/commands/*.md` (personal)
- `.claude/skills/*/SKILL.md` (skills also create slash commands)

## Notes

- Skills are the primary, richer extension mechanism; slash commands are the legacy,
  simpler format.

## Sources

- https://code.claude.com/docs/en/slash-commands
