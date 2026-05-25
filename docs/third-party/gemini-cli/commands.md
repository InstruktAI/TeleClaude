---
description: Gemini and Antigravity CLI Commands
id: third-party/gemini-cli/commands
scope: project
type: third-party
---

# Gemini and Antigravity CLI Commands

## Overview

The CLIs provide built-in commands and support custom commands defined as TOML files. Custom command files map to slash commands by path.

## Custom command locations

| Custom Commands | Gemini CLI Location | Antigravity CLI Location (`agy`) |
| :--- | :--- | :--- |
| **User Global** | `~/.gemini/commands/` | `~/.gemini/antigravity-cli/commands/` |
| **Project Local** | `.gemini/commands/` | `.agents/commands/` |

## Namespacing

- `commands/foo.toml` → `/foo`
- `commands/git/commit.toml` → `/git:commit`

## Sources

- https://geminicli.com/docs/cli/commands
- https://geminicli.com/docs/cli/custom-commands
- https://antigravity.google/docs/gcli-migration
