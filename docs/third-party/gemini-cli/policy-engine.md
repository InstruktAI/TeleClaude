---
description: 'SUPERSEDED by Antigravity CLI (agy) — legacy Gemini CLI reference only. Gemini CLI Policy Engine — the supported replacement for the deprecated --allowed-tools flag and tools.allowed setting.'
---

# Gemini CLI Policy Engine — Spec

> **Superseded.** The legacy Node-based Gemini CLI is obsolete; the Antigravity CLI
> (`agy`) replaces it — see `third-party/antigravity-cli/policy-engine` for the current contract.
> This document is retained as a migration reference for the legacy layout only; do not
> treat its paths or flags as current.

## What it is

The Policy Engine is Gemini CLI's tool-authorization system. It decides, per tool
call, whether to **allow**, **deny**, or **ask the user**. It is the supported
replacement for the now-deprecated `--allowed-tools` CLI flag and the
`tools.allowed` / `tools.exclude` settings keys.

Deprecation landed in **v0.30.0 (2026-02-25)**: "Added a new `--policy` flag for
user-defined policies, introduced strict seatbelt profiles, and deprecated
`--allowed-tools` in favor of the policy engine." The CLI warns that
`--allowed-tools` and `tools.allowed` are slated for **removal at 1.0**.
v0.31.0 added project-level policies, MCP server wildcards, and tool annotation
matching.

## Canonical fields

### Policy files (TOML)

Policies are defined in `.toml` files — **not** inline in `settings.json`. Each
rule is a `[[rule]]` table:

```toml
[[rule]]
toolName = "run_shell_command"   # tool name, or "*" for all tools
argsPattern = '"command":"git'    # optional substring/regex against serialized args
decision = "allow"                # "allow" | "deny" | "ask_user"
priority = 100                    # higher wins within a tier
```

- **Allow all tools:**

  ```toml
  [[rule]]
  toolName = "*"
  decision = "allow"
  priority = 100
  ```

- **Allow one named tool** (e.g. web search):

  ```toml
  [[rule]]
  toolName = "google_web_search"
  decision = "allow"
  priority = 100
  ```

- **Deny a tool** (the recommended replacement for `tools.exclude`). Globally
  denied tools (no `argsPattern`) are excluded from the model's memory entirely —
  more secure and saves context window.

### File loading and precedence

The CLI auto-discovers and combines `.toml` files from tiered locations. **No
`settings.json` registration is required for the User-tier default directory.**

| Tier      | Base | Location                             |
| --------- | ---- | ------------------------------------ |
| Admin     | 5    | system dirs / `--admin-policy` paths |
| User      | 4    | `~/.gemini/policies/*.toml`          |
| Workspace | 3    | project-level (currently disabled)   |
| Extension | 2    | extension-provided                   |
| Default   | 1    | built-in defaults                    |

Effective priority: `final_priority = tier_base + (toml_priority / 1000)`. A
User-tier rule with `priority = 100` resolves to `4.100`. Higher wins.

### Conflict resolution (files vs. rules)

Files have **no precedence; rules do.** All `.toml` files in a directory are
"loaded and combined" into a single rule pool — there is no per-file ranking and
no per-file ownership of a tool name. Resolution: "the policy engine evaluates
all rules to find the highest-priority rule that matches the tool call … the
first rule that matches determines the outcome," and once a rule matches,
evaluation stops (lower-priority rules are not considered).

Consequences for coexisting User-tier files (ours + a user's hand-authored file):

- They share the **same tier base (4)**, so the per-rule `priority` number is the
  sole differentiator. A user rule with a higher `priority` than ours wins for
  the tools it matches; a lower one loses. No file can delete or overwrite
  another file's rules — they only out-prioritize each other.
- This makes "accidental overwrite" a non-issue at the file level: deploying our
  file never clobbers a user's file and vice versa. Whose _rule_ takes effect is
  decided deterministically by priority.
- **Design lever:** the priority we stamp on our rules decides the relationship.
  A **low** priority makes our rules a permissive _baseline_ that any
  hand-authored user rule can override (fills gaps, never fights the user). A
  **high** priority makes our rules authoritative over same-tier user rules.

**Undocumented caveat:** the docs do **not** specify a tiebreaker when two
matching rules have the _same_ effective priority in the same tier (file load
order? alphabetical? last-wins?). Do not rely on equal-priority collisions
resolving predictably; stamp our rules at a priority that avoids ties with the
default/user space.

Default decisions when no rule matches: read-only tools → allowed; write tools →
`ask_user`; under `--yolo`, all tools are auto-approved via a high-priority rule.
In non-interactive mode, `ask_user` is treated as `deny`.

### Configuration surfaces that point at policy files

- **`--policy <path>`** (CLI flag): a file **or** directory path. When passed, it
  **replaces** the standard user policy directory (`~/.gemini/policies`) rather
  than merging with it — the caller takes full control of User-tier rules for
  that invocation. Introduced in PR #18500.
- **`--admin-policy <path>`**: supplemental Admin-tier (Base 5) policy paths.
- **`policyPaths`** (settings.json, array): persistent equivalent of `--policy` —
  additional policy files or directories to load.
- **`adminPolicyPaths`** (settings.json, array): persistent supplemental
  Admin-tier paths.

### Deprecated → replacement mapping

| Deprecated                        | Replacement                                                         |
| --------------------------------- | ------------------------------------------------------------------- |
| `tools.allowed: ["*"]` (settings) | a User-tier policy file with `toolName = "*"`, `decision = "allow"` |
| `tools.allowed: ["X"]` (settings) | a policy file with `toolName = "X"`, `decision = "allow"`           |
| `tools.exclude: ["X"]` (settings) | a policy rule with `toolName = "X"`, `decision = "deny"`            |
| `--allowed-tools X` (CLI flag)    | a policy file passed via `--policy <path>` (file or dir)            |
| `--yolo` (CLI flag)               | `--approval-mode=yolo` (the legacy `--yolo` spelling is deprecated) |

`--yolo` is a deprecated alias for `--approval-mode=yolo`. Approval modes:
`default` (prompt), `auto_edit` (auto-approve edits), `plan` (read-only),
`yolo` (auto-approve all). Under `yolo`, the Policy Engine auto-approves all
tool calls via a high-priority rule, so a redundant allow-all policy is
belt-and-suspenders rather than required for the yolo case.

### Current — NOT deprecated (do not migrate)

Confirmed current in the CLI reference; agents auditing for 1.0 breakage should
**not** flag these:

- `--sandbox` / `-s` — "Run in a sandboxed environment for safer execution."
- `--include-directories` — "Additional directories to include in the workspace."
- `--allowed-mcp-server-names` — MCP server allowlist (the sentinel `_none_` is a
  caller convention meaning "no servers", not a CLI feature).
- `--approval-mode` (`default` | `auto_edit` | `yolo` | `plan`) — the surviving
  approval surface; `--yolo` is the only deprecated spelling.
- `tools.sandbox`, `context.includeDirectories`, `context.fileName`,
  `tools.enableHooks`, `mcpServers` — current settings keys.

Sandbox + mounted directories + MCP-server allowlisting are how a session is
_jailed_; none of that machinery is deprecated. Only the `tools.allowed` /
`--allowed-tools` _tool-confirmation_ surface and the `--yolo` spelling move.

## Known caveats

- The public docs do **not** give the exact arity/repeatability of `--policy`
  beyond "file or directory path"; confirm against the installed CLI version's
  `--help` before relying on repeated flags.
- `--policy` replaces (does not merge with) `~/.gemini/policies` for that run.
- `tools.core` (built-in tool allowlist) remains current and is **not**
  deprecated; it is distinct from the policy engine.
- Issue #20469 reports policy rules can be ignored in non-interactive mode under
  `--approval-mode auto_edit`; verify behavior for headless/`--yolo` invocations.

## Sources

- https://geminicli.com/docs/reference/policy-engine/
- https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/policy-engine.md
- https://geminicli.com/docs/reference/configuration/
- https://geminicli.com/docs/changelogs/ (v0.30.0, v0.31.0)
- https://github.com/google-gemini/gemini-cli/pull/18500 (`--policy` flag)
- https://github.com/google-gemini/gemini-cli/issues/20469 (non-interactive caveat)
