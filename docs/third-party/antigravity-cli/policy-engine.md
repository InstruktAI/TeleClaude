---
id: third-party/antigravity-cli/policy-engine
type: third-party
scope: project
description: Antigravity CLI (agy) Policy Engine — the supported replacement for the deprecated --allowed-tools flag and tools.allowed setting.
---

# Antigravity CLI (agy) Policy Engine — Spec

## What it is

The Policy Engine is the official tool-authorization system for Google's Go-based **Antigravity CLI (`agy`)**. It determines, per tool invocation, whether to **allow**, **deny**, or **prompt the user (ask)**. It is the supported replacement for the deprecated `--allowed-tools` CLI flag and the `tools.allowed` / `tools.exclude` configuration settings.

Legacy settings and spelling deprecations took effect in **v2.0**: the Go implementation replaces `--approval-mode=yolo` and `--yolo` with `--dangerously-skip-permissions` and introduces strict, containerized sandbox profiles with absolute directory mounting boundaries.

## Canonical fields

### Policy files (TOML)

Policies are defined exclusively in `.toml` files located in dedicated policy folders—**never** inline in the `settings.json` file. Each rule is defined as a `[[rule]]` table:

```toml
[[rule]]
toolName = "run_shell_command"   # Tool name, or "*" for all tools
argsPattern = '"command":"git'    # Optional substring or regex match against serialized arguments
decision = "allow"                # "allow" | "deny" | "ask_user"
priority = 100                    # Precedence priority; higher numbers win within the same tier
```

- **Allow all tools:**

  ```toml
  [[rule]]
  toolName = "*"
  decision = "allow"
  priority = 100
  ```

- **Allow a specific tool** (e.g., Google web search):

  ```toml
  [[rule]]
  toolName = "google_web_search"
  decision = "allow"
  priority = 100
  ```

- **Deny a specific tool**:

  ```toml
  [[rule]]
  toolName = "execute_code"
  decision = "deny"
  priority = 100
  ```

  _Note: Denied tools are excluded from the model's environment context to preserve token limits and increase security._

### File loading and precedence tiers

`agy` automatically scans, loads, and combines TOML configuration files from tiered folder paths. No explicit registration inside `settings.json` is required for the default directories.

| Tier          | Base Weight | Antigravity CLI Location (`agy`)                       |
| :------------ | :---------- | :----------------------------------------------------- |
| **Admin**     | 5           | `/etc/antigravity/policies/` or `--admin-policy` paths |
| **User**      | 4           | `~/.gemini/antigravity-cli/policies/*.toml`            |
| **Workspace** | 3           | `.agents/policies/*.toml`                              |
| **Extension** | 2           | Built-in extension-provided paths                      |
| **Default**   | 1           | Standard system defaults                               |

The effective rule priority is calculated using the formula:
$$\text{final\_priority} = \text{tier\_base} + \frac{\text{toml\_priority}}{1000}$$

A User-tier rule with a TOML priority of `100` translates to an effective priority of `4.100`. The rule with the highest final priority determines the tool decision.

### Conflict resolution

- **Combined Pools**: Rules across all files within a directory are combined into a single flat evaluation pool. No single file takes precedence over another in the same directory.
- **First Match Wins**: Evaluated from highest to lowest effective priority. The first rule that matches the active tool name and arguments determines the outcome, terminating subsequent checks.
- **Equal Priority Ties**: When two conflicting rules have the identical effective priority, resolution behavior is not strictly defined. It is highly recommended to assign clear, distinct `priority` values (e.g., using `150` instead of `100` for overrides) to prevent non-deterministic behavior.

## Configuration surfaces

- **`--policy <path>`**: Replaces the standard User-tier directory (`~/.gemini/antigravity-cli/policies/`) with the specified file or folder directory for the active invocation.
- **`--admin-policy <path>`**: Mounts an additional Admin-tier (Base Weight 5) policy directory or file.
- **`policyPaths`** (array inside `settings.json`): Persistent list of custom policy files or directories to load alongside the default paths.
- **`adminPolicyPaths`** (array inside `settings.json`): Persistent list of additional Admin-tier policy paths.

## Deprecated vs. Modern Mapping

| Legacy Gemini CLI / Configuration | Modern Antigravity CLI (`agy`) Equivalent                              |
| :-------------------------------- | :--------------------------------------------------------------------- |
| `tools.allowed: ["*"]` (settings) | A User-tier policy rule with `toolName = "*"` and `decision = "allow"` |
| `tools.allowed: ["X"]` (settings) | A User-tier policy rule with `toolName = "X"` and `decision = "allow"` |
| `tools.exclude: ["X"]` (settings) | A User-tier policy rule with `toolName = "X"` and `decision = "deny"`  |
| `--allowed-tools X` (CLI flag)    | Set policy file or directory via `--policy <path>`                     |
| `--yolo` / `--approval-mode=yolo` | `--dangerously-skip-permissions` flag at runtime                       |

## Sources

- https://antigravity.google/docs/policy-engine
- https://dev.to/google/antigravity-cli-2-0
- https://antigravity.google/docs/gcli-migration
