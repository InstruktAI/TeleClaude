---
description: Kimi Code Agent Skill discovery, invocation, and installed 0.37.2 launch override behavior.
---

# Kimi Code Skills

## Discovery

Kimi Code Skills are Markdown `SKILL.md` documents with YAML frontmatter. The
vendor documents four tiers, from most to least specific: project, user, extra,
and built-in. User roots are `$KIMI_CODE_HOME/skills/` and
`~/.agents/skills/`; project roots are `.kimi-code/skills/` and
`.agents/skills/`; `extra_skill_dirs` supplies additional directories.

The installed 0.37.2 CLI accepts repeatable `--skills-dir`. Per its own help,
this replaces automatically discovered user and project directories for that
launch, rather than adding to them.

## Invocation

An ordinary external Skill is invoked with `/skill:<name>`, optionally followed
by text. The model may also invoke Skills based on their metadata; the vendor
documents `description` and `whenToUse` as inputs to that decision and allows
three nested Skill invocations. A `flow` Skill remains under the `skill:`
namespace rather than gaining a separate command namespace.

## Gaps

- No installed skill roots existed to inspect, and no Skill was invoked.
- Frontmatter validation was not exercised against the installed binary.

## Sources

- https://moonshotai.github.io/kimi-code/en/customization/skills
- https://moonshotai.github.io/kimi-code/en/reference/kimi-command.html
