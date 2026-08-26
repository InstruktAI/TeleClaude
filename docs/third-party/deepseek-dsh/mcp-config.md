---
description: DeepSeek Harness (dsh) MCP configuration — no auto-discovered project surface, but an explicit --patch mechanism can reference a project-committed file, and env-var indirection for secrets is a confirmed, vendor-documented syntax.
---

# DeepSeek Harness (dsh) — MCP configuration

## No auto-discovered project/workspace config surface

DeepSeek Harness's entire configuration system — including MCP server
mounting — is **user-home scoped by default**, never auto-discovered from a
project/repository directory. There is no file `dsh` reads automatically from
the current working directory of a project, and no equivalent of Claude
Code's `.mcp.json` or Codex's `.codex/config.toml`.

Per official docs (`deepseekdocs.com/docs/user-guide/configuration`,
corroborated by the vendor's own GitHub-Pages reference docs at
`deepseek-harness.github.io`), every _auto-loaded_ configuration surface
lives under the Harness home (`$DSH_HOME`, default `~/.dsh/`):

- `~/.dsh/profiles/{name}/` — one directory per profile (e.g. `web`,
  `headless`, or an operator-defined custom profile), each holding its own
  `cordis.patch.yml` user-mount layer.
- `~/.dsh/settings.yaml` — global settings.
- `~/.dsh/.credentials.yaml` — structured credential store (written with 0600
  permissions).
- `~/.dsh/.env` — fallback environment file.

**Layering order**, per the vendor's reference page, with a community
walkthrough quoting the same wording: "Layers apply to an empty entry list
in this order: each bundle in the profile's listed order, then the profile's
`cordis.patch.yml`, then the home-level one, then any `--patch` overlay." A
patch "targets a row by id and replace[s] its whole config, or insert[s] new
rows" — later layers override earlier ones by row id, not a deep merge.

## An explicit, non-auto-discovered project-scoped mechanism does exist

`--patch <path>` (confirmed both from the installed binary's own `--help` —
see `runtime-surface.md` — and from official/community docs) is a repeatable
CLI flag that applies an **arbitrary file path** as the topmost patch-list
overlay. The path is not constrained to `$DSH_HOME`: a community plugin
repository (`Hjjj0918/dsh-plugin-local-utilities`) documents exactly this
pattern — author a `cordis.local.yml` file **inside the project checkout**,
then invoke `dsh web --patch <absolute-path-to-that-project-file>` — i.e. a
project-committed patch file, loaded explicitly by the caller passing its
path, not discovered by `dsh` walking the working directory.

This resolves the brief's question directly: dsh has **no auto-discovery**
analogous to `.mcp.json`, but it does have a real, vendor-supported
**opt-in** project-scoping mechanism — a project-local file plus an explicit
`--patch <path>` argument on every invocation (or a wrapper script/alias that
supplies it). A generator targeting dsh can emit a project-local
`cordis.patch.yml`-shaped file and document the `--patch` invocation needed
to load it; it cannot make dsh pick that file up unattended.

**A distinct, unrelated "workspace" concept exists in dsh and must not be
conflated with this.** The vendor's reference docs describe a `workspace`
subsystem that is a runtime **session/directory-tracking record** — a stable
UUID, a canonical realpath, a title, and a session ledger — explicitly
described as "a host-side optional capability outside the agent loop,
invisible to the model (no tools, no prompt text, no session events)." It
carries **no per-workspace MCP or plugin configuration scoping** at all; it
is unrelated to `cordis.patch.yml` layering or to the `--patch` mechanism
above.

## MCP server schema — confirmed via official docs

MCP servers are mounted as `@deepseek-ai/dsh-mcp-client` plugin instances
inside a `cordis.patch.yml` (or `.yaml`) at any layer above; one plugin
instance = one MCP server. Tool names surface as
`mcp__<serverName>__<rawName>`, normalized to the harness's function-name
contract (≤64 chars, `[A-Za-z0-9_-]`) with a 12-digit hex hash appended on
collision. Confirmed field reference, from the official `features/mcp` page:

```yaml
- id: mcp-github
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: github
    transport: stdio
    command: npx
    args: ['-y', '@modelcontextprotocol/server-github']
    env:
      GITHUB_TOKEN: !!js process.env.GITHUB_TOKEN
```

```yaml
- id: mcp-web
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: web
    transport: streamable-http
    url: http://localhost:3000/mcp
    headers:
      Authorization: !!js '`Bearer ${process.env.MCP_TOKEN}`'
```

| Field                      | Transport       | Required | Notes                                                      |
| -------------------------- | --------------- | -------- | ---------------------------------------------------------- |
| `transport`                | both            | yes      | `"stdio"` or `"streamable-http"`                           |
| `serverName`               | both            | yes      | tool-name namespace, `[A-Za-z0-9_-]{1,32}`, must be unique |
| `command`                  | stdio           | yes      | executable to launch                                       |
| `args`                     | stdio           | no       | arguments passed to `command`                              |
| `env`                      | stdio           | no       | extra env vars, merged with host environment               |
| `cwd`                      | stdio           | no       | subprocess working directory                               |
| `url`                      | streamable-http | yes      | MCP server address (not `serverUrl`)                       |
| `headers`                  | streamable-http | no       | extra request headers                                      |
| `toolCallTimeoutMs`        | both            | no       | per-call timeout, default `60000`                          |
| `failOnStartupError`       | both            | no       | reject activation on connection failure, default `false`   |
| `reconnect.enabled`        | both            | no       | default `true`                                             |
| `reconnect.initialDelayMs` | both            | no       | default `500`                                              |
| `reconnect.maxDelayMs`     | both            | no       | default `30000`                                            |
| `reconnect.maxAttempts`    | both            | no       | default `10`                                               |

The `id`/`name`/`config` plugin-row wrapper, both transports' full field
sets, and the reconnection knobs are confirmed verbatim from the vendor's
`features/mcp` page.

## Confirmed secret-free credential syntax: `!!js`

The `!!js` YAML tag is a **first-party Cordis config-loader feature**
(processed by `@deepseek-ai/cordis-plugin-include`, documented in the
vendor's own `cordis-primer` reference page — not a dsh-specific invention),
confirmed by the exact
`env: { GITHUB_TOKEN: !!js process.env.GITHUB_TOKEN }` and
``headers: { Authorization: !!js '`Bearer ${process.env.MCP_TOKEN}`' }``
examples on the `features/mcp` page, and the general mechanism description on
the `cordis-primer` page. The tag parses the YAML scalar into a **JavaScript
expression node** rather than a literal string; the loader interpolates a
plugin's `config` field (and, separately, its `disabled` field) at mount
time, evaluated against that plugin's context. This is documented as
**allowed only in `config` and `disabled`** — not in other row metadata.

**This is a genuine secret-free declaration shape for the target use case.**
Both `env` (stdio) and `headers` (streamable-http) can hold a
`!!js process.env.<VAR_NAME>` (or a template-literal composition of it)
instead of a literal secret value — the file references an environment
variable **name**, not its value, and the value is resolved from the process
environment at load time, analogous in intent to Codex's
`env_vars`/`bearer_token_env_var` named-field convention, but expressed as a
general (if narrowly-scoped) JS-expression tag rather than a dedicated field.
A generator targeting dsh can therefore emit `!!js process.env.<VAR_NAME>` in
both `env` and `headers` and avoid materializing a literal secret in the
committed file — provided the named environment variable is actually present
in the process that ultimately runs `dsh` (this is out-of-band, exactly as
with every other CLI's env-var-reference mechanism).

## Sources

- https://deepseekdocs.com/docs/user-guide/configuration
- https://deepseekdocs.com/en/docs/user-guide/plugins
- https://deepseekdocs.com/en/docs/features/mcp — canonical stdio/HTTP MCP
  examples and field table, including the confirmed `!!js` syntax
- https://deepseek-harness.github.io/deepseek-harness/en/reference/ —
  official reference docs (vendor GitHub-Pages site), layering order
- https://deepseek-harness.github.io/deepseek-harness/en/reference/cordis-primer
  — official `!!js` tag mechanism and scope restrictions
- https://deepseek-harness.github.io/deepseek-harness/reference/subsystems/workspace
  — official docs on the unrelated session/directory-tracking `workspace`
  concept
- https://deepseek-harness.github.io/deepseek-harness/en/reference/config-catalog
  — confirms `dsh-mcp-client` plugin config surface and that `workspaceContext`
  (a different, sibling plugin) is unrelated to MCP scoping
- https://github.com/Hjjj0918/dsh-plugin-local-utilities (community) —
  concrete `--patch <project-file-path>` invocation pattern
- https://findharness.com/blog/deepseek-harness-cordis-patch-yml-explained
  (community) — corroborates the four-layer patch stack wording
- https://github.com/deepseek-ai/deepseek-harness

## See Also

- docs/third-party/deepseek-dsh/runtime-surface.md
