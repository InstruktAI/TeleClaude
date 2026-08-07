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

## Sources

- https://antigravity.google/docs/cli-permissions
- https://antigravity.google/docs/cli-settings
