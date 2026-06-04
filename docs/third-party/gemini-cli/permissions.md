---
description: Gemini and Antigravity CLI Permissions — Spec
id: third-party/gemini-cli/permissions
scope: project
type: third-party
---

# Gemini and Antigravity CLI Permissions — Spec

## Purpose

Define the configuration surface for Gemini CLI and its successor **Antigravity CLI (`agy`)** sandboxing. This spec details the CLI flags, settings paths, and JSON configuration files required to run these agents in a strict, isolated environment with explicit directory mounts.

## Sandbox Activation

The CLIs are **unrestricted by default**. Sandboxing must be explicitly enabled using one of the following methods.

### 1. CLI Flag (Recommended)

Use the `--sandbox` flag at runtime. This forces the session into a containerized or restricted environment.

```bash
# Legacy Gemini
gemini --sandbox

# Antigravity
agy --sandbox
```

### 2. Environment Variable

Set `GEMINI_SANDBOX` to `true`.

```bash
export GEMINI_SANDBOX=true
agy
```

### 3. Settings File (`settings.json`)

Enable it persistently in the user's `settings.json`.

```json
{
  "tools": {
    "sandbox": true
  }
}
```

## Directory Mounting

When sandboxing is active, the agent cannot access files outside the launch directory. To grant access to specific external resources (like global docs), use the `--include-directories` (or `--add-dir` for `agy`) flags.

### Syntax

Pass a comma-separated list of absolute paths (Gemini) or repeat the directory additions (Antigravity).

```bash
# Legacy Gemini
gemini --sandbox --include-directories ~/.teleclaude/docs,/tmp/shared

# Antigravity (using --add-dir or --include-directories)
agy --sandbox --add-dir ~/.teleclaude/docs --add-dir /tmp/shared
```

## Configuration File Locations

Settings are loaded in this precedence order (overrides lower entries):

| Configuration Surface      | Gemini CLI Location       | Antigravity CLI Location (`agy`)                                   |
| :------------------------- | :------------------------ | :----------------------------------------------------------------- |
| **User Global Settings**   | `~/.gemini/settings.json` | `~/.gemini/antigravity-cli/settings.json`                          |
| **Project Local Settings** | `.gemini/settings.json`   | `.agents/antigravity-cli/settings.json` or `.agents/settings.json` |
| **MCP Servers Config**     | Inline in `settings.json` | `mcp_config.json` in the respective setting folder                 |

### Authentication & Consent Files

- **Legacy Gemini**: Credentials are stored in `~/.gemini/oauth_creds.json` (Google OAuth2).
- **Antigravity CLI (`agy`)**: Caches credentials securely in the **system native keyring** (macOS Keychain, etc.). No plain text file is written.

## Example: Secure Worker Invocation

To launch a worker restricted to CWD but with access to shared documentation:

```bash
# Legacy Gemini
gemini --sandbox --include-directories ~/.teleclaude/docs --yolo

# Antigravity CLI
agy --sandbox --add-dir ~/.teleclaude/docs --approval-mode=yolo
```

- `--sandbox`: Enforces filesystem isolation.
- `--include-directories` / `--add-dir`: Explicitly mounts the docs folder into the sandbox.
- `--approval-mode=yolo` (replaces deprecated `--yolo`): Auto-approves tool execution within the sandbox, relying on sandboxing for safety.

## Sources

- https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/sandbox.md
- https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/configuration.md
- https://antigravity.google/docs/gcli-migration
- https://context7.com/google-gemini/gemini-cli/llms.txt
