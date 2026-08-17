---
description: Codex CLI Skills — discovery locations, `$name` invocation, structure, and what the vendor documentation does not specify.
---

# Codex CLI Skills

## Overview

Skills are the vendor's recommended mechanism for reusable instructions; custom prompts
are deprecated in their favour (see `third-party/codex-cli/commands`). A skill is a
directory containing a `SKILL.md`.

## Locations

Two sources describe skill roots and they do not list the same paths. Both are recorded
here as found.

**Published documentation** (`learn.chatgpt.com/docs/build-skills`) gives this precedence
order:

1. `$CWD/.agents/skills` — repository, current working directory
2. `$CWD/../.agents/skills` — repository, parent folder
3. `$REPO_ROOT/.agents/skills` — repository root
4. `$HOME/.agents/skills` — user scope
5. `/etc/codex/skills` — admin scope
6. System bundled skills shipped by OpenAI

`$CODEX_HOME/skills` and `~/.codex/skills` do not appear on that page.

**Shipped CLI, version 0.147.0.** The bundled `skill-creator` and `skill-installer` skills
install user skills into `$CODEX_HOME/skills/<skill-name>`, falling back to
`~/.codex/skills` when `CODEX_HOME` is unset, and describe that path as automatically
discovered:

> "Installs into `$CODEX_HOME/skills/<skill-name>` (defaults to `~/.codex/skills`)."

> "…default to `$CODEX_HOME/skills`; when `CODEX_HOME` is unset, fall back to
> `~/.codex/skills` so the skill is auto-discovered."

OpenAI's own bundled skills ship in `$CODEX_HOME/skills/.system/` — on this installation
`imagegen`, `openai-docs`, `plugin-creator`, `review-agent`, `skill-creator`, and
`skill-installer`. `$HOME/.agents/skills` does not exist on this installation.

## Invocation

Skills are mentioned with a dollar prefix: `$skill-name`. The vendor states: "In Codex CLI
or the IDE extension, run `/skills` or type `$` to mention a skill."

The documentation does not describe skills being registered as slash commands.

## Arguments

The documentation specifies no syntax for passing arguments on the skill invocation line,
and no argument-substitution mechanism inside `SKILL.md` — no `$ARGUMENTS`, no `{{args}}`,
no placeholder of any kind.

## Skill structure

- Required: `SKILL.md`, carrying the instructions and metadata.
- Optional: `scripts/`, `references/`, `assets/`, `agents/` subdirectories.
- Required frontmatter: `name` (the identifier) and `description` (when the skill should
  and should not trigger). Bundled skills additionally carry an optional
  `metadata.short-description`.

## Sources

- https://learn.chatgpt.com/docs/build-skills — current page; `https://developers.openai.com/codex/skills` 308-redirects here
- https://developers.openai.com/codex/team-config
