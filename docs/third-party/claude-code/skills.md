# Claude Code Skills

## Overview

Skills are the primary extension mechanism for Claude Code. Skills can be invoked by the
model when relevant or explicitly via `/skill-name`.

## Locations and precedence

Claude Code discovers skills in multiple locations (highest priority first):

- Enterprise-managed skills
- Personal skills in `~/.claude/skills/<skill-name>/SKILL.md`
- Project skills in `.claude/skills/<skill-name>/SKILL.md`
- Plugin skills in `<plugin>/skills/<skill-name>/SKILL.md` (namespaced)

## Skill format

A skill is a folder containing `SKILL.md` with YAML frontmatter and Markdown instructions.
Supporting files (examples, templates, scripts) can live alongside `SKILL.md`.

## Sources

- https://code.claude.com/docs/en/skills
