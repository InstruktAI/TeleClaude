---
description: Claude Code project-scoped MCP configuration — .mcp.json schema, ${VAR} expansion, approval/trust gating, and scope precedence.
---

# Claude Code — Project-scoped MCP configuration

## File and top-level shape

Project scope stores MCP servers in `.mcp.json` at the project root, under the
`mcpServers` key:

```json
{
  "mcpServers": {
    "shared-server": {
      "type": "http",
      "url": "https://example.com/mcp"
    }
  }
}
```

Committing `.mcp.json` shares the server set with the whole team via version
control.

## Per-server fields

An entry with no `type` is read as **stdio**. An entry with a `url` and no
`type` is a configuration error (Claude Code skips it and logs a warning as of
v2.1.202; before that it reported a confusing `command: expected string,
received undefined`).

- **stdio**: `command` (string), `args` (string[]), `env` (map<string,string>),
  plus optional `timeout` (ms, per-server tool-execution timeout, overrides
  `MCP_TOOL_TIMEOUT`).
- **http** (`"type": "http"`, alias `"streamable-http"`) / **sse**
  (`"type": "sse"`, deprecated) / **ws** (`"type": "ws"`): `url` (string),
  `headers` (map<string,string>), `headersHelper` (shell command producing
  dynamic headers — see below), `timeout`, `alwaysLoad`. `ws` accepts the same
  `url`/`headers`/`headersHelper`/`timeout`/`alwaysLoad` fields as `http` but
  has no `claude mcp add --transport` equivalent — it's JSON/`add-json` only.
  OAuth-specific: `oauth.authServerMetadataUrl`, `oauth.scopes` (single
  space-separated string, RFC 6749 §3.3 format; takes precedence over
  discovered scopes).
- Reserved server names Claude Code refuses to load or `claude mcp add`
  rejects: `workspace`, `claude-in-chrome`, `computer-use`,
  `Claude Preview`, `Claude Browser`.

Claude Code injects `CLAUDE_PROJECT_DIR` (the project root) into a spawned
stdio server's own environment — not into Claude Code's environment — so a
`${CLAUDE_PROJECT_DIR}` reference in `command`/`args` needs a fallback default
(`${CLAUDE_PROJECT_DIR:-.}`) unless the entry comes from a plugin, which
substitutes it directly.

## `${VAR}` expansion contract

Claude Code expands environment-variable references inside `.mcp.json`
values. Confirmed expansion locations: `command`, `args`, `env`, `url`,
`headers`.

- `${VAR}` — expands to `VAR` from Claude Code's own process environment.
- `${VAR:-default}` — expands to `VAR` if set, else the literal `default`.
- If a referenced variable is unset and has no default, the config **still
  loads**: the unexpanded `${VAR}` text is used as-is, and `claude mcp list`
  reports a missing-variable warning for that server. This is not a hard
  failure.

```json
{
  "mcpServers": {
    "api-server": {
      "type": "http",
      "url": "${API_BASE_URL:-https://api.example.com}/mcp",
      "headers": { "Authorization": "Bearer ${API_KEY}" }
    }
  }
}
```

Practical implication for generated configs: a literal secret never has to
land in `.mcp.json` — reference the variable name and let Claude Code's own
launching environment supply the value.

## Approval / trust gating for project-scoped servers

Beyond generic workspace trust (accepting the trust dialog for the folder),
project-scoped `.mcp.json` servers carry a **second, independent approval
gate** — per-server, not per-folder:

- Interactive sessions prompt for approval before first use of each
  `.mcp.json` server. `claude mcp reset-project-choices` clears prior
  approval/rejection choices.
- `claude -p`, Agent SDK sessions, and Claude Code-on-the-web (cloud) sessions
  **cannot show the prompt** — Claude Code loads project-scoped servers there
  without asking. A session started in `bypassPermissions` mode with
  `skipDangerousModePermissionPrompt` also skips it.
- Approval state is recorded via settings keys, resolved as: `boolean
enableAllProjectMcpServers` (approve every server in the project's
  `.mcp.json` without prompting), `enabledMcpjsonServers: string[]` (approve
  specific server names), `disabledMcpjsonServers: string[]` (reject specific
  names — this one **always** rejects, in every mode, regardless of scope).
  All three are valid in any settings file (`.claude/settings.json`,
  `.claude/settings.local.json`, `~/.claude/settings.json`, managed settings,
  or `--settings`).
- **Interaction with workspace trust (as of v2.1.196):** in an **untrusted**
  folder, `claude mcp list`/`claude mcp get` read `.mcp.json` approvals only
  from settings sources that are _not checked into the repo_ — i.e. a cloned
  repo cannot self-approve its own MCP servers. `enableAllProjectMcpServers`
  or `enabledMcpjsonServers` committed to the project's `.claude/settings.json`
  is **ignored** until the folder is trusted; the server sits at
  `⏸ Pending approval` instead of connecting. Approvals from `~/.claude/settings.json`,
  managed settings, and `--settings` still apply in an untrusted folder.
  `.claude/settings.local.json` approvals apply too, but only once Claude Code
  can confirm (via `git`) that the file is untracked — and that check itself
  requires the folder be trusted first (except inside the user's own config
  home). `disabledMcpjsonServers` rejects a server from any settings file
  regardless of trust state.
- To keep project servers out unconditionally, use `disabledMcpjsonServers`,
  or exclude project settings entirely with `--setting-sources` (CLI) /
  `settingSources` (SDK option).

## Scope precedence

Three named scopes plus two external sources, in this exact connect order
(first match wins; **fields are never merged across scopes** — the whole
winning entry is used):

1. **Local** — `~/.claude.json`, under that project's path; private, default
   scope for `claude mcp add`.
2. **Project** — `.mcp.json` at project root; shared via VCS.
3. **User** — `~/.claude.json`, top level; available in every project.
4. Plugin-provided servers.
5. claude.ai connectors.

Local/Project/User match duplicates by server **name**; plugins and connectors
match by **endpoint** (same URL/command as a higher-precedence entry counts as
a duplicate). Desktop app's Code tab is a documented exception: if the same
stdio server name exists in both `~/.claude.json` (user scope) and
`.mcp.json`, the Code tab specifically prefers the `~/.claude.json` definition.

## Sources

- https://code.claude.com/docs/en/mcp
- https://code.claude.com/docs/en/settings
- https://code.claude.com/docs/en/settings-reference
