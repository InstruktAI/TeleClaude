---
description: Antigravity CLI (agy) Commands and Flags
---

# Antigravity CLI (agy) Commands and Flags

## Overview

`agy` is the official Go-based terminal agent harness for Google's Antigravity 2.0 platform. Unlike the legacy Node-based Gemini CLI, the Go implementation uses modern, simplified CLI flags and stores session configurations in the system keyring.

## Command-Line Usage

```
Usage of agy:
  --add-dir                       Add a directory to the workspace (repeatable) (default [])
  -c                              Short alias for --continue
  --continue                      Continue the most recent conversation
  --conversation                  Resume a previous conversation by ID
  --dangerously-skip-permissions  Auto-approve all tool permission requests without prompting
  -i                              Short alias for --prompt-interactive
  --log-file                      Override CLI log file path
  --model                         Model for the current CLI session
  -p                              Short alias for --print
  --print                         Run a single prompt non-interactively and print the response
  --print-timeout                 Timeout for print mode wait (default 5m0s)
  --prompt                        Alias for --print
  --prompt-interactive            Run an initial prompt interactively and continue the session
  --sandbox                       Run in a sandbox with terminal restrictions enabled
```

## Security Profiles and Permissions

- **Auto-Approval**: To auto-approve tool permission requests without interactive prompts, use the `--dangerously-skip-permissions` flag (replaces legacy `--approval-mode=yolo`).
- **Sandbox Mode**: Use the `--sandbox` flag along with `--add-dir <path>` to run in a restricted terminal environment.

## Session Resumption

- **Resume specific session**: Use `--conversation <session_id>` (replaces legacy `--resume <session_id>`).
- **Continue latest session**: Use `--continue` or `-c` (replaces legacy `--resume latest` or `--continue`).

## Model Selection

- **Command-line model**: The Go-based `agy` CLI accepts `--model` for the current CLI session.
- **Stored model defaults**: Model tiering and configurations are also loaded via global settings files under `~/.gemini/antigravity-cli/settings.json` or managed dynamically in the TUI configuration adapter.

## Custom commands: superseded by skills

`agy` has **no standalone custom-commands directory.** The vendor plugin/skills
documentation describes no `~/.gemini/antigravity-cli/commands/` path; custom commands
are superseded by the skills and plugins model.

Skills are the command surface: a Markdown skill in the user-global skills directory is
"automatically imported as a global slash command whenever you launch `agy`", and
registered skills convert into slash commands in the TUI (a skill named `refactor-ui` is
invoked as `/refactor-ui`).

| Extension surface        | Antigravity CLI Location (`agy`)                   |
| :----------------------- | :------------------------------------------------- |
| **Skills — user global** | `~/.gemini/antigravity-cli/skills/`                |
| **Skills — workspace**   | `.agents/skills/`                                  |
| **Plugins**              | `~/.gemini/antigravity-cli/plugins/<plugin_name>/` |

To expose a reusable instruction set as a slash command in `agy`, author it as a skill.

## Sources

- https://antigravity.google/docs/cli/plugins
- https://antigravity.google/docs/gcli-migration
- https://dev.to/google/antigravity-cli-2-0

## See Also

- third-party/antigravity-cli/research-log — Antigravity Local Language Server Quota Summary
