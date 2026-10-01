---
description: Antigravity CLI permission resources and terminal sandbox filesystem behavior.
---

# Antigravity CLI permissions

## Purpose

Record the CLI's permission resources, approval settings, and terminal
sandbox boundary as separate vendor controls.

## Permission resources

Antigravity evaluates sensitive operations as `action(target)` resources.
Supported CLI actions include `read_file`, `write_file`, `read_url`,
`execute_url`, `command`, `unsandboxed`, and `mcp`. Deny rules take precedence
over ask rules, which take precedence over allow rules. A global `*` target
matches every target in its action namespace.

`toolPermission` selects an approval preset independently of the permission
rules. `artifactReviewPolicy` is a separate artifact-approval setting.
`allowNonWorkspaceAccess` controls whether file tools can reach outside
recognized workspaces. `--dangerously-skip-permissions` auto-approves tool
permission requests; it does not itself describe a filesystem sandbox.

## Terminal sandbox

`enableTerminalSandbox` or the `--sandbox` flag enables OS isolation for
agent-run terminal commands. On macOS the CLI uses Seatbelt; on Linux it uses
namespaces. The permission engine supplies the sandbox's mounts: `read_file`
grants add read-only paths, and `write_file` grants add read-write paths.
Domains granted through `read_url` populate the sandbox's network allowlist.

An `unsandboxed(...)` allow rule runs matching commands outside the terminal
sandbox without prompting. The global `unsandboxed(*)` form matches every
command. `write_file(*)` matches every file target and supplies a broad
read-write mount. These grants change the effective sandbox boundary even
when terminal sandboxing is enabled.

## Gaps / Unknowns

- The installed CLI 1.2.14 rejects `unsandboxed(*)` in the user
  `settings.json` permission rules at startup as an invalid rule that grants
  nothing, and directs the user to `command(...)` instead. The vendor pages
  cited below listed `unsandboxed` as an action when this summary was written;
  whether it was retired or renamed is unresolved.
- The combined effective behavior of `--sandbox`,
  `--dangerously-skip-permissions`, and wildcard `write_file` or `unsandboxed`
  rules has not been exercised against the installed CLI.

## Sources

- https://antigravity.google/docs/permissions?tab=cli
- https://antigravity.google/docs/sandbox?tab=cli
- https://antigravity.google/docs/cli/reference/
