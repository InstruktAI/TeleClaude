---
id: third-party/antigravity-cli/permissions
scope: project
description: Current Antigravity CLI permission and execution settings used by TeleClaude.
---

# Antigravity CLI permissions

## Purpose

Record the current global JSON configuration surface for running Google's
Antigravity CLI (`agy`) without interactive tool or artifact approval gates.

## Global settings

Antigravity reads user-level settings from
`~/.gemini/antigravity-cli/settings.json`. The settings relevant to autonomous
operation are top-level keys:

```json
{
  "toolPermission": "always-proceed",
  "artifactReviewPolicy": "always-proceed",
  "allowNonWorkspaceAccess": true,
  "enableTerminalSandbox": false,
  "permissions": {
    "allow": [
      "read_file(*)",
      "write_file(*)",
      "read_url(*)",
      "execute_url(*)",
      "command(*)",
      "unsandboxed(*)",
      "mcp(*)"
    ],
    "ask": [],
    "deny": []
  }
}
```

`permissions` uses action resources. The supported broad resource forms are
`read_file(*)`, `write_file(*)`, `read_url(*)`, `execute_url(*)`, `command(*)`,
`unsandboxed(*)`, and `mcp(*)`. Deny rules take precedence over allow rules,
and ask rules retain an interactive approval boundary.

`toolPermission` and `artifactReviewPolicy` remove the two independent approval
gates. `allowNonWorkspaceAccess` permits filesystem access beyond the active
workspace. `enableTerminalSandbox` controls terminal sandboxing.

Workspace trust is a separate Antigravity state surface. TeleClaude does not
author or automate project-folder trust; workspace and worktree inheritance
remain owned by Antigravity.

TeleClaude also launches `agy` with `--dangerously-skip-permissions`. The flag
and the persisted JSON settings intentionally agree so both managed sessions
and direct invocations use the same autonomous permission posture.

## Terminal sandbox and file-tool boundary

The CLI's terminal sandbox uses OS isolation for agent-run commands. On macOS
it uses Seatbelt; on Linux it uses namespaces. The sandbox receives read-only
paths from `read_file` grants and read-write paths from `write_file` grants.
The file tools themselves are governed by the permission engine, which applies
`Deny > Ask > Allow` to their path targets. Approval posture and filesystem
reach are therefore separate settings.

An `unsandboxed(...)` allow rule lets matching commands execute outside the
terminal sandbox without a prompt. The global `unsandboxed(*)` form matches
every command. `write_file(*)` grants file-tool writes throughout the host and
also broadens the terminal sandbox's read-write mounts. Consequently, setting
`enableTerminalSandbox` to `true` while retaining those wildcard grants does
not establish a worktree write boundary. `--dangerously-skip-permissions`
auto-approves permission requests; it is not evidence of filesystem
containment.

## Gaps / Unknowns

- The combined effective behavior of a per-session `--sandbox` launch with
  persisted wildcard grants and `--dangerously-skip-permissions` has not been
  verified in the installed CLI. Inspect the resolved permissions and prove a
  denied write to a sibling worktree before depending on that combination.

## Sources

- https://antigravity.google/docs/permissions?tab=cli
- https://antigravity.google/docs/sandbox?tab=cli
- https://antigravity.google/docs/cli/reference/
