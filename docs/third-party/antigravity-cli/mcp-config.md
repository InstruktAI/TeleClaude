---
description: Antigravity CLI MCP configuration surfaces — global vs workspace-scoped mcp_config.json, schema, and the confirmed absence of a secret-free credential syntax.
---

# Antigravity CLI — MCP configuration

## File locations

Two locations, stated directly and unambiguously by the official Antigravity
docs, and cross-confirmed across three separate vendor pages fetched in this
pass (`/docs/cli/mcp/`, `/docs/mcp/`, `/docs/ide/mcp/` — the IDE page
explicitly documents the same two-tier structure as the CLI page):

- **Global** — `~/.gemini/config/mcp_config.json` — MCP server definitions
  available across all projects, and shared across all three surfaces (IDE,
  CLI, SDK): "configure a server once and every surface picks it up."
- **Workspace-scoped** — `.agents/mcp_config.json`, resolved relative to the
  active project — project-specific server definitions. The docs describe
  the split as the two "separated into dedicated, sparse configurations."
  This is the current, vendor-documented, project-scoped surface; treat it as
  the authoritative path.
- **Not a config file, but adjacent** — `~/.gemini/antigravity/mcp_oauth_tokens.json`
  persists OAuth access tokens for authenticated servers (global, not
  per-workspace). A community source additionally reports per-surface
  **derived-cache** directories (`~/.gemini/antigravity/mcp/`,
  `~/.gemini/antigravity-cli/mcp/`, `~/.gemini/antigravity-ide/mcp/`) that
  must be cleared, not just the source file edited, for a removed server to
  actually disappear — unconfirmed against an official page, noted for
  operational awareness only, not part of the config contract itself.

A separate, differently-named path — `<workdir>/.antigravitycli/mcp_config.json`
— is the subject of an open upstream report, GitHub issue
`google-antigravity/antigravity-cli#60` (filed against v1.0.0, confirmed still
open with no maintainer reply on a follow-up pass): that path's `mcpServers`
field is discovered and logged but silently ignored at load time — only
HOME-level entries actually initialize. The issue thread itself never mentions
`.agents/mcp_config.json`; its paths are exclusively `.antigravitycli/` and the
HOME-level file. That directory name (`.antigravitycli/`) does not match the
vendor-documented workspace path (`.agents/`) at any version consulted here,
so this is most plausibly a distinct/legacy surface, not evidence against the
documented `.agents/mcp_config.json` path — noted for completeness, not as a
live doubt about the documented mechanism.

**Genuinely open gap, re-confirmed on a follow-up search pass:** the docs do
not state precedence or merge behavior when the same server name is defined
in both the global and workspace files, and no community source located
(GitHub issues, dev.to, atamel.dev, agentpedia.codes) resolves it either. One
low-reliability community source (`agentpedia.codes`) additionally claims only
a single central config location exists at all — this directly contradicts
all three vendor pages fetched here (each of which documents the workspace
file explicitly) and is not credited.

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

The official `/docs/cli/mcp/` and `/docs/mcp/` pages document **no
`${VAR}`-style expansion syntax anywhere** — not in `env`, not in `headers`,
not in any other field. This was confirmed on a direct, exhaustive fact-pass
over both pages (every field, every credential mechanism, every example), not
inferred from a single missed example. Credentials are handled by one of four
documented mechanisms, none of which involve string interpolation:

- **`env`** (stdio only) — a literal `map<string,string>` set directly in the
  process environment of the spawned server. Values are literal strings
  written into the file. A community report from a Google Cloud Developer
  Expert, writing about hands-on use of this exact field, states plainly that
  referencing an environment variable here "isn't working for me and I've had
  to hard-code these keys" — firsthand corroboration, not just an absent
  vendor example, that there is no working indirection for `env` in practice.
- **`authProviderType: "google_credentials"`** (remote) — delegates to Google
  Application Default Credentials, configured out-of-band via
  `gcloud auth application-default login` (and
  `gcloud auth application-default set-quota-project <project>` for quota).
  No token or secret is ever written into `mcp_config.json` under this path.
- **`oauth: { clientId, clientSecret }`** (remote) — OAuth client
  credentials; resulting access tokens persist separately in
  `~/.gemini/antigravity/mcp_oauth_tokens.json`, not in the server config
  itself. When the target MCP server supports **Dynamic Client Registration
  (DCR)**, the docs state **no `oauth` configuration is needed at all** — the
  client registers itself against the server's own DCR endpoint, using the
  fixed redirect URI `https://antigravity.google/oauth-callback`. This is a
  third fully secret-free path, but conditional on the target server
  implementing DCR — it is not available for an arbitrary remote server.
- **`headers`** (remote) — the docs' own examples place bearer tokens and API
  keys **directly as literal string values** in this object. This is the
  vendor-documented pattern for a header-authenticated remote server; there
  is no field-name or syntax alternative offered for keeping that value out
  of the file.

One low-reliability community source (`agentpedia.codes`) claims `env` values
support `${VAR_NAME}` substitution (`"SUPABASE_URL": "${SUPABASE_URL}"`) and
recommends sourcing the real value from a shell profile or `.env` file. This
claim is **not credited**: it is contradicted by (a) two independently fetched
official vendor pages that exhaustively enumerate the field with no such
syntax, and (b) the firsthand community report above from a named author who
tried environment-variable indirection in this exact field and had to
hard-code the value instead. It is recorded here only because the research
brief calls for surfacing community claims explicitly labeled as such — this
one does not survive that labeling and must not be encoded into a generator.

**Conclusion for generation purposes:** Antigravity CLI has a confirmed
**absence** of a secret-free interpolation mechanism for `headers` (the
common case for bearer-token auth) and for `env`, corroborated by firsthand
community use, not merely by an absent example. The only secret-free paths
are the two credential-delegation mechanisms above (`google_credentials`, and
OAuth when the target server supports DCR), which apply only when the target
server's auth model matches one of them. A project-scoped native publisher
that needs to reference an arbitrary secret in `headers` or `env` has no
documented way to avoid writing it literally into `.agents/mcp_config.json`
— this is a real fail-closed condition for the target use case, not an
unresolved question.

## Trust / approval gating for workspace config

The MCP docs page does not describe a distinct approval or trust prompt for
_loading_ `.agents/mcp_config.json` itself. It does document a related but
different gate: **per-tool execution approval** — "unconfigured MCP tools run
in **Ask** mode" by default, requiring approval before each tool call, with
access-control patterns `mcp(server/tool)`, `mcp(server/*)`, and `mcp(*)`.
That is a runtime tool-execution gate, not a config-file-loading trust gate.
A follow-up search pass (GitHub issues, community write-ups, both the CLI and
IDE vendor pages) found no additional source describing a load-time trust
step for the workspace file either. Whether file loading is additionally
covered by the general workspace-trust mechanism in
`directory-trust-1.1.12.md` — whose own key-normalization and inheritance
rules are themselves an open gap in that document — remains unestablished.

## Known gaps

- No documented precedence/merge rule when the same server name is defined
  in both the global (`~/.gemini/config/mcp_config.json`) and workspace
  (`.agents/mcp_config.json`) files — re-confirmed absent after a dedicated
  follow-up search; no vendor page or community source resolves it.
- No documented per-server approval/trust step for _loading_
  `.agents/mcp_config.json`, distinct from the per-tool "Ask mode" execution
  gate and from general workspace trust — re-confirmed absent after a
  follow-up search.
- The `.antigravitycli/mcp_config.json` GitHub issue (a differently-named
  path from v1.0.0) was not confirmed to be related to, or superseded by,
  the current `.agents/mcp_config.json` surface — noted for completeness
  only; see File locations. The issue remains open with no maintainer reply.
- The per-surface derived-cache directories reported by a community source
  (`~/.gemini/antigravity{,-cli,-ide}/mcp/`) were not corroborated against an
  official page — noted for operational awareness only.

## Sources

- https://antigravity.google/docs/cli/mcp/
- https://antigravity.google/docs/mcp/
- https://antigravity.google/docs/ide/mcp/
- https://antigravity.google/docs/cli/using?app=cli
- https://github.com/google-antigravity/antigravity-cli/issues/60
- https://atamel.dev/posts/2026/07-10_where_agy_mcp_servers/ (community — MCP
  server cache directories; precedence/trust not documented there either)
- https://dev.to/gde/configuring-mcp-servers-and-skills-for-antigravity-cli-and-ide-2bh0
  (community, Google Cloud Developer Expert author — firsthand report that
  `env` variable references do not work in practice and require hard-coding)
- https://agentpedia.codes/blog/antigravity-mcp-tutorial (community, low
  reliability — contradicted `${VAR_NAME}` substitution claim not credited;
  see Environment-variable / credential reference syntax)

## See Also

- docs/third-party/antigravity-cli/directory-trust-1.1.12.md
