---
description: Claude Code permission rules and the separate Bash sandbox filesystem boundary.
---

# Claude Code Permissions — Spec

## Purpose

Record Claude Code's distinct shell sandbox and built-in file-tool permission
surfaces.

## Distinct enforcement surfaces

Claude Code's Bash sandbox applies OS-level filesystem and network restrictions
to Bash, PowerShell, and Monitor commands and their child processes. It does
not run the built-in Read, Edit, or Write tools inside that sandbox. Those file
tools use Claude Code's permission system directly. Computer-use and external
tool surfaces have their own boundaries.

Sandbox mode and permission mode are independent. The sandbox's auto-allow mode
approves commands that run inside it without prompting; regular permissions
mode retains command prompts. Neither mode turns the Bash sandbox into a
process-wide filesystem boundary. `--dangerously-skip-permissions` suppresses
tool approval checks and protected-path checks; it does not expand the Bash
sandbox to built-in file tools.

## Bash sandbox filesystem

On macOS, the built-in Bash sandbox uses Seatbelt. On Linux and WSL2 it uses
Bubblewrap. Sandboxed commands can write to the working directory, the
per-user temporary directory, and directories added through `--add-dir`,
`/add-dir`, or `permissions.additionalDirectories`. These added directories are
writable. `sandbox.filesystem.allowWrite` grants specific additional write
paths; `denyWrite` and `denyRead` narrow access.

For a linked Git worktree, the Bash sandbox also permits writes to the main
repository's shared `.git` directory so ordinary Git commands can update the
worktree index, objects, and refs. Writes to Git `hooks/` and `config` remain
denied. The main checkout's source files do not become writable merely because
the worktree shares that Git directory.

`sandbox.allowUnsandboxedCommands` defaults to an escape path: Claude can retry
a blocked command outside the sandbox through the permission flow. When set to
`false`, that retry is disabled. With `sandbox.failIfUnavailable` unset or
`false`, missing sandbox dependencies can cause commands to run unsandboxed;
`true` makes sandbox setup failure fatal. A command listed in
`sandbox.excludedCommands` runs outside the Bash sandbox.

## File-tool permissions

Read and Edit permission rules govern the built-in file tools. A `deny` rule
overrides an `allow` rule. Permission rules are a separate tool decision layer,
not OS confinement of an arbitrary command or child process.

## Gaps / Unknowns

- The effective path grants of a particular session depend on merged managed,
  user, project, local, and CLI settings. No particular merged configuration
  has been exercised here.

## Sources

- https://code.claude.com/docs/en/sandboxing
- https://code.claude.com/docs/en/permissions
- https://code.claude.com/docs/en/settings
