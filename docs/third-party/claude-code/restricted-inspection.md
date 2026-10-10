---
id: third-party/claude-code/restricted-inspection
scope: project
description: Claude Code native subscription authentication and restricted file-tool inspection, including managed-policy exceptions.
---

# Restricted subscription inspection

Claude Code supports non-interactive print mode with JSON-schema output. The
long-lived token produced by `claude setup-token` authenticates subscription
model requests through `CLAUDE_CODE_OAUTH_TOKEN`. Bare mode does not read that
variable. `CLAUDE_CONFIG_DIR` selects separate runtime configuration and state.

Restricted mode confines built-in file tools to working directories and rejects
permission bypass. `--tools` selects the built-in tool set; `--allowedTools`
only changes approval behavior. Read, Glob and Grep can navigate prepared files
without a shell. MCP tools are separately controlled by strict configuration
and tool denials.

Safe mode suppresses discovered customizations while retaining authentication.
Managed settings still apply, including policy-provided executable helpers.
Restricted mode and the outside-working-directory read setting have
version-specific availability; the latter has runtime configuration exceptions.
These are native tool controls, not a process-wide kernel boundary or evidence
that a particular hosted invocation has been validated.

The maintained GitHub Action supports subscription tokens, but its automation
setup configures GitHub access and replaces checkout credentials. Checkout
non-persistence does not remove those later effects. Native CLI inspection of
prepared local evidence does not require that GitHub integration.

## Sources

- https://code.claude.com/docs/en/authentication#generate-a-long-lived-token
- https://code.claude.com/docs/en/cli-reference
- https://code.claude.com/docs/en/permissions#working-directories
- https://code.claude.com/docs/en/sandboxing
- https://github.com/anthropics/claude-code-action/blob/1d6de8cb0c237e7c15e9e1bdf973826ebae490cc/src/github/operations/git-config.ts
