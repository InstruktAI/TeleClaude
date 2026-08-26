---
description: Antigravity CLI MCP configuration surfaces — global vs workspace-scoped mcp_config.json, schema, and the confirmed absence of a secret-free credential syntax.
---

# Antigravity CLI — MCP configuration

## File locations

Two locations, stated directly and unambiguously by the official Antigravity
CLI MCP docs (`antigravity.google/docs/cli/mcp/`):

- **Global** — `~/.gemini/config/mcp_config.json` — MCP server definitions
  available across all projects.
- **Workspace-scoped** — `.agents/mcp_config.json`, resolved relative to the
  active project — project-specific server definitions. The docs describe
  the split as the two "separated into dedicated, sparse configurations."
  This is the current, vendor-documented, project-scoped surface; treat it as
  the authoritative path.
- **Not a config file, but adjacent** — `~/.gemini/antigravity/mcp_oauth_tokens.json`
  persists OAuth access tokens for authenticated servers (global, not
  per-workspace).

A separate, differently-named path — `<workdir>/.antigravitycli/mcp_config.json`
— is the subject of an open upstream report, GitHub issue
`google-antigravity/antigravity-cli#60` (filed against v1.0.0): that path's
`mcpServers` field is discovered and logged but silently ignored at load
time. That directory name (`.antigravitycli/`) does not match the
vendor-documented workspace path (`.agents/`) at any version consulted here,
so this is most plausibly a distinct/legacy surface, not evidence against the
documented `.agents/mcp_config.json` path — noted for completeness, not as a
live doubt about the documented mechanism.

**Genuinely open gap:** the docs do not state precedence or merge behavior
when the same server name is defined in both the global and workspace files.

## Schema

```json
{
  "mcpServers": {
    "local-server": {
      "command": "node",
      "args": ["/path/to/executable.js"],
      "env": { "SQLITE_DB_PATH": "/var/data/app.db" },
      "cwd": "/optional/working/dir"
    },
    "remote-server": {
      "serverUrl": "https://api.example.com/mcp/",
      "headers": { "Authorization": "Bearer TOKEN" }
    }
  }
}
```

- **stdio**: `command` (string), `args` (string[]), `env` (map<string,string>),
  `cwd` (string, optional).
- **remote**: `serverUrl` (string, required for Streamable HTTP or SSE — the
  docs are explicit that the legacy field names `url` and `httpUrl` are
  **not** supported; `serverUrl` is the only accepted key), `headers`
  (map<string,string>).
- **Common to both**: `authProviderType` (documented value:
  `"google_credentials"`), `oauth` (object with `clientId`/`clientSecret`),
  `disabled` (boolean — disable without removing the entry),
  `disabledTools` (string[] — withhold specific tools).
- A CLI-owned management surface exists (`mcp add`/`remove`/`list`/`enable`/
  `disable` subcommands with `--type`, `--env`, `--header` flags) that edits
  the **user-level** `mcp_config.json` without hand-editing; it is not
  documented as writing the workspace-scoped file.

## Environment-variable / credential reference syntax — no expansion syntax exists

The official `/docs/cli/mcp/` page documents **no `${VAR}`-style expansion
syntax anywhere** — not in `env`, not in `headers`, not in any other field.
This was confirmed on a direct, exhaustive fact-pass over the page (every
field, every credential mechanism, every example), not inferred from a single
missed example. Credentials are handled by one of three documented
mechanisms, none of which involve string interpolation:

- **`env`** (stdio only) — a literal `map<string,string>` set directly in the
  process environment of the spawned server. Values are literal strings
  written into the file.
- **`authProviderType: "google_credentials"`** (remote) — delegates to Google
  Application Default Credentials, configured out-of-band via
  `gcloud auth application-default login` (and
  `gcloud auth application-default set-quota-project <project>` for quota).
  No token or secret is ever written into `mcp_config.json` under this path.
- **`oauth: { clientId, clientSecret }`** (remote) — OAuth client
  credentials; resulting access tokens persist separately in
  `~/.gemini/antigravity/mcp_oauth_tokens.json`, not in the server config
  itself.
- **`headers`** (remote) — the docs' own examples place bearer tokens and API
  keys **directly as literal string values** in this object. This is the
  vendor-documented pattern for a header-authenticated remote server; there
  is no field-name or syntax alternative offered for keeping that value out
  of the file.

**Conclusion for generation purposes:** Antigravity CLI has a confirmed
**absence** of a secret-free interpolation mechanism for `headers` (the
common case for bearer-token auth) and for `env`. The only secret-free paths
are the two credential-delegation mechanisms above (`google_credentials` /
OAuth), which apply only when the target server's auth model matches one of
them. A project-scoped native publisher that needs to reference an arbitrary
secret in `headers` or `env` has no documented way to avoid writing it
literally into `.agents/mcp_config.json` — this is a real fail-closed
condition for the target use case, not an unresolved question.

## Trust / approval gating for workspace config

The MCP docs page does not describe a distinct approval or trust prompt for
_loading_ `.agents/mcp_config.json` itself. It does document a related but
different gate: **per-tool execution approval** — "unconfigured MCP tools run
in **Ask** mode" by default, requiring approval before each tool call. That
is a runtime tool-execution gate, not a config-file-loading trust gate.
Whether file loading is additionally covered by the general workspace-trust
mechanism in `directory-trust-1.1.12.md` — whose own key-normalization and
inheritance rules are themselves an open gap in that document — is not
established here.

## Known gaps

- No documented precedence/merge rule when the same server name is defined
  in both the global (`~/.gemini/config/mcp_config.json`) and workspace
  (`.agents/mcp_config.json`) files.
- No documented per-server approval/trust step for _loading_
  `.agents/mcp_config.json`, distinct from the per-tool "Ask mode" execution
  gate and from general workspace trust.
- The `.antigravitycli/mcp_config.json` GitHub issue (a differently-named
  path from v1.0.0) was not confirmed to be related to, or superseded by,
  the current `.agents/mcp_config.json` surface — noted for completeness
  only; see File locations.

## Sources

- https://antigravity.google/docs/cli/mcp/
- https://antigravity.google/docs/mcp/
- https://antigravity.google/docs/cli/using?app=cli
- https://github.com/google-antigravity/antigravity-cli/issues/60

## See Also

- docs/third-party/antigravity-cli/directory-trust-1.1.12.md
