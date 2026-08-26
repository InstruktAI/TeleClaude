---
description: DeepSeek Harness (dsh) has no project-scoped MCP (or any) config surface — everything resolves under the user-home Harness directory.
---

# DeepSeek Harness (dsh) — No project-scoped MCP configuration surface

## Finding

DeepSeek Harness's entire configuration system — including MCP server
mounting — is **user-home scoped**, never project/repository scoped. There is
no file `dsh` auto-discovers from the current working directory of a project,
and no equivalent of Claude Code's `.mcp.json` or Codex's `.codex/config.toml`.

Per official docs (`deepseekdocs.com/docs/user-guide/configuration`), every
configuration surface lives under the Harness home (`$DSH_HOME`, default
`~/.dsh/`):

- `~/.dsh/profiles/{name}/` — one directory per profile (e.g. `web`,
  `headless`, or an operator-defined custom profile), each holding its own
  `cordis.patch.yml` user-mount layer.
- `~/.dsh/settings.yaml` — global settings.
- `~/.dsh/.credentials.yaml` — structured credential store (written with 0600
  permissions).
- `~/.dsh/.env` — fallback environment file.

Layering order (bundle → profile → machine-wide → CLI flag):
each bundle's own `cordis.patch.yml`, then the profile's `cordis.patch.yml`,
then `$DSH_HOME/cordis.patch.yml` (machine-wide), then any `--patch <path>`
files passed on the command line. This confirms and extends what the local
runtime-surface research already established: `--patch` is an explicit,
operator-supplied CLI flag (see `runtime-surface.md`), not an implicit
project-root discovery mechanism — there is no path in this layering chain
rooted at a project's working directory.

MCP servers are mounted as `@deepseek-ai/dsh-mcp-client` plugin instances
inside a `cordis.patch.yml` at one of the layers above (one plugin instance =
one MCP server; tools surface as `mcp__<serverName>__<rawName>`). Wherever
that mount is authored, it lands in a **user-home-scoped** file, not a
project-committed one.

## Implication for project-scoped native publication

There is nothing to generate here: dsh has no project-root config file this
research could locate, official or otherwise, that a TeleClaude project-local
MCP publisher could target. Native publication for dsh, if ever supported,
would have to write into `$DSH_HOME` (a specific profile's `cordis.patch.yml`
or the machine-wide one) — which is a **global/per-machine** surface, not a
per-project one, and out of scope for "project-scoped" generation as defined
by this research brief.

## Known gaps

- The exact schema fields for the `dsh-mcp-client` plugin instance (stdio
  `command`/`args`/`env`, remote `url`/`headers`) were not confirmed against
  an official page during this pass — one fetch of a features/mcp page
  returned an example using `!!js process.env.VAR` for env-var injection, but
  this could not be corroborated against the official plugins/configuration
  pages fetched afterward, which show no such syntax. **Treat that specific
  syntax claim as unverified** — do not encode it into a generator without
  independent confirmation (e.g. reading the shipped `dsh-mcp-client` plugin
  source).
- No official page consulted here documents a generic `${VAR}` interpolation
  mechanism for `cordis.patch.yml` values; the one credential-reference
  pattern shown (`apiKeyEnv: <ENV_VAR_NAME>`) is a named-field convention
  similar to Codex's `env_vars`/`bearer_token_env_var`, not general string
  interpolation. This parallel is suggestive, not confirmed for the MCP
  plugin specifically.
- `$DSH_HOME`'s unset default was already an open gap in
  `runtime-surface.md`; the docs above imply `~/.dsh/` but this wasn't
  independently re-verified against the binary in this pass.

## Sources

- https://deepseekdocs.com/docs/user-guide/configuration
- https://deepseekdocs.com/en/docs/user-guide/plugins
- https://deepseekdocs.com/en/docs/features/mcp (env-var syntax claim unverified — see Known gaps)
- https://github.com/deepseek-ai/deepseek-harness

## See Also

- docs/third-party/deepseek-dsh/runtime-surface.md
