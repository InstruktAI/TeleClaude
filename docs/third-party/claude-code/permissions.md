---
description: Claude Code permission rules and the separate Bash sandbox filesystem boundary.
---

# Claude Code Permissions — Spec

## Purpose

Record how Claude Code confines shell commands and built-in file tools, and
which controls can keep an autonomous linked-worktree session inside its
assigned filesystem boundary.

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
tool approval checks and protected-path checks, so the Bash sandbox alone
cannot confine built-in file edits under that flag.

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
a blocked command outside the sandbox through the permission flow. Set it to
`false` to prevent that retry. `sandbox.failIfUnavailable` must be `true` when
startup without a working sandbox should fail rather than continue
unsandboxed. A command listed in `sandbox.excludedCommands` is outside the
Bash sandbox; that list needs separate review.

## File-tool permissions

Read and Edit permission rules govern the built-in file tools. A `deny` rule
overrides an `allow` rule. Permission rules are a separate tool decision layer,
not OS confinement of an arbitrary command or child process. A launch that
uses bypass-permissions mode cannot rely on those rules to prevent an Edit or
Write call from targeting another worktree.

## Gaps / Unknowns

- The built-in Bash sandbox plus permission rules is not one OS-level boundary
  around every Claude Code tool. A complete worker boundary must account for
  built-in file edits and any tools outside Bash separately.
- A session's effective rules depend on merged managed, user, project, local,
  and CLI settings. The resolved configuration needs inspection in the running
  version before relying on a particular path grant or denial.

## Sources

- https://code.claude.com/docs/en/sandboxing
- https://code.claude.com/docs/en/permissions
- https://code.claude.com/docs/en/settings
