---
description: Codex CLI project-scoped MCP configuration — [mcp_servers.<id>] TOML schema, env_vars whitelisting, and trusted-project gating.
---

# Codex CLI — Project-scoped MCP configuration

## File and scoping

Codex reads `[mcp_servers.<id>]` tables from the same layered TOML config
surface used for every other Codex setting — no separate MCP-specific file.
Project scope is `.codex/config.toml`, searched from the repository root down
to the current working directory; user scope is `~/.codex/config.toml`
(`$CODEX_HOME/config.toml`). The closer file wins on a key-by-key basis when
both define the same key — i.e. project-level `mcp_servers` entries take
precedence over user-level ones for the same server id (this is the general
config-layering rule; `mcp_servers` is not itself special-cased).

`mcp_servers` is **not** on Codex's restricted-key list, so it is fully
settable at project scope. What _is_ restricted from project override:
`openai_base_url`, `chatgpt_base_url`, `apps_mcp_product_sku`,
`model_provider`, `model_providers`, `notify`, `profile`, `profiles`,
`experimental_realtime_ws_base_url`, `otel` — these stay user/machine-scoped
regardless of what a project `.codex/config.toml` declares.

## Trusted-project gating

Project-level `.codex/config.toml` — including `mcp_servers` defined there —
loads **only for a trusted project**. For an untrusted project, Codex ignores
the entire project `.codex/` layer (config, hooks, rules) outright; nothing
partially loads. Trust is a separate per-project decision recorded against
the resolved main Git repository root (see the project's
`directory-trust-0.147.0.md` for the storage/resolution mechanics); the
sandbox/approval-bypass flag (`--dangerously-bypass-approvals-and-sandbox`)
does **not** satisfy or bypass this trust gate.

## `[mcp_servers.<id>]` schema

### Stdio transport

```toml
[mcp_servers.<id>]
command = "npx"
args = ["-y", "some-mcp-server"]
cwd = "."
env = { KEY = "literal-value" }
env_vars = ["GITHUB_TOKEN", { name = "REMOTE_TOKEN", source = "remote" }]
enabled = true
required = false
startup_timeout_sec = 10
tool_timeout_sec = 60
experimental_environment = "local"   # or "remote"
enabled_tools = ["tool_a"]
disabled_tools = ["tool_b"]
default_tools_approval_mode = "auto" # auto | prompt | writes | approve

[mcp_servers.<id>.tools.<tool>]
approval_mode = "prompt"             # per-tool override
```

### Streamable-HTTP transport

```toml
[mcp_servers.<id>]
url = "https://mcp.example.com/mcp"
auth = "oauth"                       # oauth (default) | chatgpt
bearer_token_env_var = "MCP_TOKEN"
http_headers = { "X-Static" = "value" }
env_http_headers = { "Authorization" = "MCP_AUTH_HEADER_ENV_VAR" }
oauth_resource = "..."               # RFC 8707 resource parameter
scopes = ["read", "write"]
enabled = true
required = false
default_tools_approval_mode = "auto"
enabled_tools = []
disabled_tools = []
```

## Environment-variable reference semantics — no `${VAR}` interpolation

Codex does **not** interpolate `${VAR}`-style placeholders inside TOML string
values for `mcp_servers`. Instead it uses **named-reference fields**, each
resolved by Codex's own process at spawn/connect time — the config file never
needs to carry a literal secret:

- `env` — a literal `map<string,string>` of environment variables set
  (forwarded as-is) into the spawned stdio server's process. Values written
  here are literal strings in the TOML file; do not put secrets in `env`
  directly.
- `env_vars` — an **allowlist of variable names** (string shorthand, or
  `{ name, source }` objects) that Codex forwards from its own resolved
  environment into the spawned server. `source = "local"` (default) reads
  from Codex's local process environment; `source = "remote"` reads from the
  remote-executor environment when `experimental_environment = "remote"`.
  This is the sanctioned secret-free mechanism: the TOML names the variable,
  the actual value lives only in the environment Codex runs in.
- `bearer_token_env_var` — names the env var whose value becomes the
  `Authorization: Bearer <value>` header for a streamable-HTTP server.
- `env_http_headers` — a map of **header name → env var name**; the header
  value is read from that named environment variable at connect time, never
  written literally into the TOML.
- `http_headers` — the literal-value counterpart to `env_http_headers`; values
  here are literal strings in the file (same caveat as `env`).

Net effect for fail-closed generation: use `env_vars` (stdio) or
`bearer_token_env_var`/`env_http_headers` (HTTP) to reference secrets by
name; never populate `env`/`http_headers` with anything sensitive.

## Sources

- https://developers.openai.com/codex/mcp (redirects to https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
- https://developers.openai.com/codex/config-basic
- https://developers.openai.com/codex/config-advanced (redirects to https://learn.chatgpt.com/docs/config-file/config-advanced)
- https://learn.chatgpt.com/docs/config-file/config-reference
