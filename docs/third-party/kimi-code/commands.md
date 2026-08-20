---
description: 'Kimi Code 0.37.2 command surfaces: CLI flags and subcommands, TUI slash commands, and dynamic Skill commands.'
---

# Kimi Code Commands

## Overview

The installed Kimi Code CLI is version 0.37.2. Its top-level command supports
interactive sessions and one-shot prompt mode (`-p`); its visible subcommands
are `export`, `provider`, `acp`, `web`, `server` (deprecated), `login`,
`doctor`, `vis`, `migrate`, and `upgrade`/`update`.

`provider` has `add`, `remove`, `list`, and `catalog` operations. `doctor`
validates `config.toml` or `tui.toml`; `export` writes a session ZIP; `acp`
serves Agent Client Protocol over stdio; and `vis` opens a local session
visualizer.

## Interactive commands

Slash commands are TUI controls, not shell subcommands. Typing `/` opens
completion; an unrecognized slash-prefixed input is sent to the agent as a
normal message. The vendor reference groups the built-ins around account and
configuration, session management, modes/run control, and status. `/status`,
`/mcp`, `/plugins`, `/version`, and `/feedback` are documented as always
available; commands that mutate session state can be unavailable while output
is streaming or context is compacting.

Skills add commands dynamically. Ordinary external Skills use
`/skill:<name> [extra text]`; built-in Skills appear directly as `/<name>`;
and a sub-skill can use `<parent>.<child>`.

## Gaps

- The installed CLI's interactive completion list was not exhaustively
  captured, so this document does not claim an exhaustive 0.37.2 slash-command
  inventory.
- Hidden aliases and commands not printed by `kimi --help` were not relied on.

## Sources

- https://moonshotai.github.io/kimi-code/en/reference/kimi-command.html
- https://moonshotai.github.io/kimi-code/en/reference/slash-commands.html
