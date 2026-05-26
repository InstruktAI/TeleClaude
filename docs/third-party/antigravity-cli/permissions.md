---
description: Antigravity CLI (agy) Permissions and Sandboxing Spec
id: third-party/antigravity-cli/permissions
scope: project
type: third-party
---

# Antigravity CLI (agy) Permissions and Sandboxing Spec

## Purpose

Define the configuration surface for Google's **Antigravity CLI (`agy`)** sandboxing and runtime security models. This spec details the CLI flags, settings paths, and keyring authentication behavior required to run `agy` in a secure, isolated container with whitelisted directory boundaries.

## Sandbox Activation

The CLI is **unrestricted by default**. Sandboxing must be explicitly enabled using one of the following methods:

### 1. Command-Line Flag (Recommended)

Use the `--sandbox` flag at runtime. This forces the session into a containerized sandbox with system/network restrictions enabled.

```bash
agy --sandbox
```

### 2. Environment Variable

Set `AGY_SANDBOX` to `true`.

```bash
export AGY_SANDBOX=true
agy
```

### 3. Settings File (`settings.json`)

Enable it persistently in the user's `settings.json` file.

```json
{
  "tools": {
    "sandbox": true
  }
}
```

## Directory Mounting

When sandboxing is active, the agent cannot access files outside the launch directory. To grant access to specific external resources (such as global documentation), use the `--add-dir` flag (repeatable).

### Syntax

```bash
agy --sandbox --add-dir ~/.teleclaude/docs --add-dir /tmp/shared
```

## Configuration File Locations

Settings are loaded in this precedence order (overrides lower entries):

| Configuration Surface      | Antigravity CLI Location (`agy`)                                   |
| :------------------------- | :----------------------------------------------------------------- |
| **User Global Settings**   | `~/.gemini/antigravity-cli/settings.json`                          |
| **Project Local Settings** | `.agents/antigravity-cli/settings.json` or `.agents/settings.json` |
| **MCP Servers Config**     | `mcp_config.json` in `~/.gemini/antigravity-cli/`                  |

### Authentication & Keyring

Unlike the legacy Gemini CLI, which stored OAuth2 credentials in plaintext (`~/.gemini/oauth_creds.json`), `agy` leverages the **native system keyring** (macOS Keychain, etc.) to cache tokens securely. No plaintext files containing credentials are created or written by `agy` under the hood.

## Example: Secure Worker Invocation

To launch a worker restricted to the workspace but with access to shared documentation and auto-approval enabled:

```bash
agy --sandbox --add-dir ~/.teleclaude/docs --dangerously-skip-permissions
```

- `--sandbox`: Enforces filesystem isolation.
- `--add-dir`: Mounts the documentation folder into the sandbox.
- `--dangerously-skip-permissions` (replaces legacy `--approval-mode=yolo`): Auto-approves tool execution within the sandbox boundaries.

## Sources

- https://antigravity.google/docs/gcli-migration
- https://dev.to/google/antigravity-cli-2-0
