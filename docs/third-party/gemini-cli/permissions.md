# Gemini CLI Permissions — Spec

## Purpose

Define the configuration surface for Gemini CLI sandboxing. This spec details the CLI flags and JSON settings required to run Gemini in a strict, isolated environment with explicit directory mounts.

## Sandbox Activation

The Gemini CLI is **unrestricted by default**. Sandboxing must be explicitly enabled using one of the following methods.

### 1. CLI Flag (Recommended)

Use the `--sandbox` (or `-s`) flag at runtime. This forces the session into a containerized or restricted environment (depending on OS support).

```bash
gemini --sandbox
```

### 2. Environment Variable

Set `GEMINI_SANDBOX` to `true`.

```bash
export GEMINI_SANDBOX=true
gemini
```

### 3. Settings File (`settings.json`)

Enable it persistently in `~/.gemini/settings.json`.

```json
{
  "tools": {
    "sandbox": true
  }
}
```

## Directory Mounting

When sandboxing is active, the agent cannot access files outside the launch directory. To grant access to specific external resources (like global docs), use the `--include-directories` flag.

### Syntax

Pass a comma-separated list of absolute paths.

```bash
gemini --sandbox --include-directories /Users/username/.teleclaude/docs,/tmp/shared
```

### Runtime Mounting

During a session, the user (or orchestrator) can grant access dynamically:

```bash
/directory add /path/to/resource
```

## Configuration File Locations

Gemini CLI loads settings in this precedence order (overrides lower entries):

1.  `/etc/gemini-cli/settings.json` (System Override)
2.  `.gemini/settings.json` (Project Local)
3.  `~/.gemini/settings.json` (User Global)
4.  `/etc/gemini-cli/system-defaults.json` (System Defaults)

## Example: Secure Worker Invocation

To launch a worker restricted to CWD but with access to shared documentation:

```bash
gemini --sandbox --include-directories ~/.teleclaude/docs --yolo
```

- `--sandbox`: Enforces filesystem isolation.
- `--include-directories`: Explicitly mounts the docs folder into the sandbox.
- `--yolo`: Allows the agent to run commands _within the sandbox_ without asking for confirmation (autonomy), relying on the sandbox for safety.

## Sources

- https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/sandbox.md
- https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/configuration.md
- https://context7.com/google-gemini/gemini-cli/llms.txt
