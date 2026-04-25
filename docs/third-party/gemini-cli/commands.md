---
description: Gemini CLI Commands
id: third-party/gemini-cli/commands
scope: project
type: third-party
---

# Gemini CLI Commands

## Overview

Gemini CLI provides built-in commands and supports custom commands defined as TOML files.
Custom command files map to slash commands by path.

## Custom command locations

- `.gemini/commands/` (project)
- `~/.gemini/commands/` (user)

## Namespacing

- `commands/foo.toml` → `/foo`
- `commands/git/commit.toml` → `/git:commit`

## Sources

- https://geminicli.com/docs/cli/commands
- https://geminicli.com/docs/cli/custom-commands
