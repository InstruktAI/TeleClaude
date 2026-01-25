# Agent Artifacts (Overview) — Reference

Required reads

@~/.teleclaude/docs/baseline/reference/agent-schema.md
@~/.teleclaude/docs/baseline/reference/skill-schema.md
@~/.teleclaude/docs/baseline/reference/command-schema.md

## What this is

This reference groups the schemas for agent artifacts and explains how discovery
and selection depend on their metadata.

## Canonical artifacts

- Agents: `agents/<name>.md`
- Skills: `skills/<skill-name>/SKILL.md`
- Commands: `commands/<name>.md`

## Discovery and selection

- Runtimes scan these folders and extract frontmatter.
- Frontmatter is used for matching, routing, and visibility.
- Clear, task-oriented descriptions improve selection accuracy.

## Authoring intent

- Use stable names and precise descriptions.
- Write metadata for _selection_, not marketing.
- Keep artifacts narrow and purpose-specific.
