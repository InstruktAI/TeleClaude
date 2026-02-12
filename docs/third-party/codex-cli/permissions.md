# Codex CLI Permissions — Spec

## Purpose

Define the security configuration for the Codex CLI (`gpt-5.3-codex`). This tool uses a "profile" system to manage the balance between autonomy (approvals) and safety (sandboxing).

## Configuration File

Settings are stored in TOML format at `~/.codex/config.toml`.

## Profiles & Autonomy

Codex uses **profiles** to define behavior. You can switch profiles at runtime or configure a default.

### Standard Profiles

| Profile     | Sandboxed? | Approvals Required? | Network? | Description                                 |
| :---------- | :--------- | :------------------ | :------- | :------------------------------------------ |
| `safe`      | **Yes**    | **Always**          | No       | Maximum security. Asks for everything.      |
| `default`   | **Yes**    | **Modifications**   | Yes      | Asks for writes/exec. Reads are silent.     |
| `full-auto` | **Yes**    | **Never**           | No       | Autonomous. Restricted to CWD. No internet. |
| `danger`    | **No**     | **Never**           | Yes      | **Unrestricted.** No sandbox, no approvals. |

### Configuration Example (`config.toml`)

```toml
[profiles.worker]
sandbox = true
require_approval = false
allow_network = false
restrict_to_cwd = true
allowed_paths = ["/Users/username/.teleclaude/docs"]
```

## CLI Flags

### Enforcing Restriction

To run a worker safely, you must **REMOVE** the bypass flag and specify a restrictive mode or profile.

**Dangerous (Current):**

```bash
codex --dangerously-bypass-approvals-and-sandbox
```

**Secure (Recommended):**

```bash
# Uses 'full_auto' logic (sandbox + CWD restriction + no approvals)
codex --profile full_auto
```

### Search Capability

The `--search` flag allows the agent to use a search tool. This is generally safe to include even in restricted modes as it is a read-only information retrieval tool.

```bash
codex --profile full_auto --search
```

## Example: Secure Worker Invocation

```bash
codex --profile full_auto --search
```

This command launches Codex in a mode where:

1.  It can execute code and write files without nagging the user (`require_approval = false`).
2.  It cannot touch files outside CWD (`sandbox = true`, `restrict_to_cwd = true`).
3.  It can search the web (`--search`).

## Sources

- https://openai.com/codex-cli-docs
- Inferred internal wrapper behavior for `gpt-5.3-codex`.
