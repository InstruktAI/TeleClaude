# Claude Code Permissions — Spec

## Purpose

Define the configuration surface for restricting Claude Code CLI file access. This spec provides the exact JSON schema and CLI flags required to confine an agent to its Current Working Directory (CWD) while allowing explicit, controlled mounts.

## Configuration Hierarchy

Claude Code merges settings from multiple sources. For role-based gating, we primarily use the **User Settings** or **Project Settings** combined with **CLI Arguments**.

1.  **Managed Settings** (`/etc/claude-code/` or equivalent): Immutable enterprise policies.
2.  **CLI Arguments**: Session-specific flags (e.g., `--add-dir`).
3.  **Local Project**: `.claude/settings.local.json` (Ignored by git).
4.  **Shared Project**: `.claude/settings.json` (Versioned).
5.  **User Settings**: `~/.claude/settings.json` (Global defaults).

## Permission Configuration (`settings.json`)

To enforce a "CWD-only" sandbox, use the `permissions` object in `settings.json`. The `deny` rules take precedence over `allow`.

### Restricted Worker Profile

This configuration blocks access to parent directories and sensitive system paths, effectively jailing the agent to the CWD and its subdirectories.

**File:** `~/.claude/settings.json` (or project-level `.claude/settings.json`)

```json
{
  "permissions": {
    "deny": [
      "Read(../*)",
      "Read(../**)",
      "Edit(../*)",
      "Edit(../**)",
      "Bash(cd ..*)",
      "Bash(ls ..*)",
      "Read(/etc/**)",
      "Read(/usr/**)",
      "Read(/Users/**)",
      "Read(/var/**)"
    ],
    "allow": ["Read(*)", "Read(**/*)", "Edit(*)", "Edit(**/*)", "Bash(*)"]
  }
}
```

### Allow-Listing Additional Directories

To allow a worker to access specific external directories (e.g., global documentation) while maintaining the restriction, use the `allow` block for those specific absolute paths.

```json
{
  "permissions": {
    "allow": ["Read(/Users/username/.teleclaude/docs/**)"]
  }
}
```

**Note:** If a `deny` rule overlaps with an `allow` rule (e.g., `Read(/Users/**)` vs `Read(/Users/username/.teleclaude/docs/**)`), the **deny rule wins**. You must refine the deny rules to exclude the allowed paths (e.g., deny specific siblings of the home dir instead of the root).

## CLI Flags

### Restricting Access

**Critical:** You must **REMOVE** the `--dangerously-skip-permissions` flag to enable the permission system.

```bash
# BAD (Unrestricted)
claude --dangerously-skip-permissions

# GOOD (Restricted, respects settings.json)
claude
```

### Mounting Directories

To explicitly mount a directory for a session (making it visible and readable), use `--add-dir`.

```bash
claude --add-dir /Users/username/.teleclaude/docs
```

This flag does **not** override `deny` rules. If you deny `Read(/Users/**)`, `--add-dir` will not make the path readable. You must align the JSON config with the mount points.

## Example: Secure Worker Invocation

To launch a worker that is restricted to CWD but can read global docs:

1.  **Config (`settings.json`):**
    ```json
    {
      "permissions": {
        "deny": ["Read(../*)"]
      }
    }
    ```
2.  **Command:**
    ```bash
    claude --add-dir ~/.teleclaude/docs --settings '{"forceLoginMethod": "claudeai"}'
    ```

## Sources

- https://context7.com/anthropics/claude-code/llms.txt
- https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/command-development/references/marketplace-considerations.md
