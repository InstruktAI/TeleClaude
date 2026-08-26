---
description: Antigravity CLI MCP configuration surfaces — global vs workspace-scoped mcp_config.json, schema, and unresolved env-var/trust gaps.
---

# Antigravity CLI — MCP configuration

## File locations

Two documented locations, per the official Antigravity CLI MCP docs
(`antigravity.google/docs/cli/mcp/` and `/docs/mcp/`):

- **Global** — `~/.gemini/config/mcp_config.json` (an earlier path,
  `~/.gemini/antigravity-cli/mcp_config.json`, is referenced by some
  community write-ups as a prior/migrated location; the current docs cite
  `~/.gemini/config/mcp_config.json`).
- **Workspace-scoped** — `.agents/mcp_config.json` in the active project.
  Docs state this directly: "Workspace local setups: Configured in your
  active project under `.agents/mcp_config.json`," and separately that the
  CLI/SDK "automatically discovers servers configured in your workspace's
  `.agents/mcp_config.json` file."

**This conflicts with an open, unresolved upstream report.** GitHub issue
`google-antigravity/antigravity-cli#60` (filed against v1.0.0, still open at
research time) documents a **different** project-local path —
`<workdir>/.antigravitycli/mcp_config.json` — whose `mcpServers` field is
discovered and logged but **silently ignored**: only the HOME-level config
actually spawns servers. It is not established whether `.antigravitycli/` and
`.agents/` name the same underlying feature at different CLI versions (i.e.
the path was renamed and the bug may or may not have followed it) or are two
distinct discovery paths. **Do not treat workspace-scoped loading as reliable
without a version-pinned functional verification** (an actual run showing a
`.agents/mcp_config.json`-only server connecting) before depending on it for
generated config.

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
- **remote**: `serverUrl` (string, required — note the field name is
  `serverUrl`, not `url`), `headers` (map<string,string>).
- **Common to both**: `authProviderType` (documented value:
  `"google_credentials"`), `oauth` (object with `clientId`/`clientSecret`),
  `disabled` (boolean — disable without removing the entry),
  `disabledTools` (string[] — withhold specific tools).
- A CLI-owned management surface exists (`mcp add`/`remove`/`list`/`enable`/
  `disable` subcommands with `--type`, `--env`, `--header` flags) that edits
  the **user-level** `mcp_config.json` without hand-editing; it is not
  documented as writing the workspace-scoped file.

## Environment-variable / secret reference syntax — unresolved

**No official page fetched in this research (`/docs/cli/mcp/`, `/docs/mcp/`,
`/docs/cli/using`) documents a `${VAR}`-style expansion syntax for
`mcp_config.json` values.** The `env` example shown in the docs uses a
literal value (`"SQLITE_DB_PATH": "/var/data/app.db"`), not a variable
reference.

Third-party (non-vendor) sources are split and not authoritative enough to
act on:

- One community source asserts `${VAR_NAME}` substitution is supported and
  recommended for keeping secrets out of the file.
- Another describes it as broken — "Antigravity CLI does not substitute shell
  variables" for at least the global config, requiring a manual/scripted
  rewrite of the file — and separately calls an environment-variable bug in
  the global MCP config a known "day-one paper cut."

**Conclusion for generation purposes: treat Antigravity CLI as having no
confirmed secret-free env-var reference mechanism for `mcp_config.json`.**
Until vendor documentation or source inspection (the CLI is closed-source
Go per the directory-trust research; the exact binary would need static
analysis) confirms working `${VAR}` expansion, a project-scoped native
publish for this CLI cannot assume literal secrets are avoidable via that
syntax — this is a fail-closed condition for the target use case (see Known
gaps).

## Trust / approval gating for workspace config

No official documentation found (across the pages fetched here) describes a
distinct approval or trust prompt specific to loading `.agents/mcp_config.json`
MCP servers, separate from the general workspace-trust gate documented in
`directory-trust-1.1.12.md`. That trust gate's own key-normalization and
inheritance rules are themselves an open gap per that document — so whether
trusting a workspace is sufficient to load its `.agents/mcp_config.json`
servers, or whether some further per-server approval exists, is not
established here.

## Known gaps

- Whether `.agents/mcp_config.json` reliably loads (vs. the documented-but-
  ignored `.antigravitycli/mcp_config.json` failure mode) is unverified for
  any specific shipped version.
- No confirmed `${VAR}` (or equivalent) secret-reference syntax in official
  docs; third-party reports conflict on whether such substitution even works
  where claimed.
- No documented per-server approval/trust step for workspace-scoped MCP
  servers, distinct from general workspace trust.
- The exact global path is inconsistent across sources
  (`~/.gemini/antigravity-cli/mcp_config.json` vs
  `~/.gemini/config/mcp_config.json`) — treat the latter as current per the
  fetched official docs, but re-verify per installed version before relying
  on it.

## Sources

- https://antigravity.google/docs/cli/mcp/
- https://antigravity.google/docs/mcp/
- https://antigravity.google/docs/cli/using?app=cli
- https://github.com/google-antigravity/antigravity-cli/issues/60

## See Also

- docs/third-party/antigravity-cli/directory-trust-1.1.12.md
