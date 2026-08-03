---
description: 'SUPERSEDED by Antigravity CLI (agy) — legacy Gemini CLI reference only. Gemini and Antigravity CLI Commands'
---

# Gemini and Antigravity CLI Commands

> **Superseded.** The legacy Node-based Gemini CLI is obsolete; the Antigravity CLI
> (`agy`) replaces it — see `third-party/antigravity-cli/commands` for the current contract.
> This document is retained as a migration reference for the legacy layout only; do not
> treat its paths or flags as current.

## Overview

The CLIs provide built-in commands and support custom commands defined as TOML files. Custom command files map to slash commands by path.

## Custom command locations

| Custom Commands   | Gemini CLI Location   | Antigravity CLI Location (`agy`)      |
| :---------------- | :-------------------- | :------------------------------------ |
| **User Global**   | `~/.gemini/commands/` | `~/.gemini/antigravity-cli/commands/` |
| **Project Local** | `.gemini/commands/`   | `.agents/commands/`                   |

## Namespacing

- `commands/foo.toml` → `/foo`
- `commands/git/commit.toml` → `/git:commit`

## Sources

- https://geminicli.com/docs/cli/commands
- https://geminicli.com/docs/cli/custom-commands
- https://antigravity.google/docs/gcli-migration

## See Also

- third-party/antigravity-cli/research-log — Antigravity Local Language Server Quota Summary
