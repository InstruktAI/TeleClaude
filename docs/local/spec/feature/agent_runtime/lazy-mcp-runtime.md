---
description: Daemon-owned lazy MCP runtime for on-demand server discovery, tool listing,
  and tool calls through the telec mcp surface.
visibility: public
---

# Lazy MCP Runtime — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

Lazy MCP runtime gives agents access to configured MCP servers without loading every server into every agent process at startup. The TeleClaude daemon owns MCP server leases, starts or connects to a server only when a caller asks for its tools or invokes a tool, and exposes the capability through `telec mcp` and `/mcp` API endpoints.

The TeleClaude MCP registry is the source of available servers. Server entries from `teleclaude-mcp.jsonc` and `teleclaude-mcp.local.jsonc` are accumulated into the daemon's effective MCP catalog; those source files are inputs, not mutation targets. `mcp.json` and `mcp.local.json` are compatibility import inputs during the transition window only. Each server declares whether its credential owner is global or the verified person behind the caller. Secret placeholders resolve exclusively from that owner's TeleClaude environment file at lease start; TeleClaude's registry listing and launch metadata retain placeholders rather than resolved values. MCP server tool metadata and call results remain server-controlled data and are returned unchanged.

## Canonical fields

### API surface

- `GET /mcp/servers` — returns the configured MCP server catalog with secret-safe launch metadata and activation triggers.
- `GET /mcp/servers/{slug}/tools` — lazy-initializes the server lease when needed, calls `tools/list`, caches the tool catalog, and returns it.
- `POST /mcp/servers/{slug}/tools/{tool}/call` — lazy-initializes the server lease when needed, sends `tools/call` with the supplied JSON arguments, and returns the tool result.

### CLI surface

- `telec mcp list [--exclude <slug> ...]` — prints configured server slugs with activation triggers.
- `telec mcp list-tools <slug>` — prints the server's current tool catalog, initializing the daemon-owned lease on first use.
- `telec mcp call <slug> <tool> --json '<arguments>'` — invokes one tool through the daemon-owned lease and returns the MCP tool result.

Human-readable server listing prints each slug and its optional activation
trigger only. JSON and API catalog responses may include secret-safe launch
metadata and referenced variable names, never resolved secret values.

### Runtime ownership

- The daemon owns stdio child processes and remote MCP sessions. Agents never receive raw stdio pipes, session identifiers, or secret-expanded launch commands.

- Managed MCP servers use the lazy runtime exclusively; native agent MCP configs are not a publication target, and setup removes TeleClaude-managed entries from them.

- A lease is keyed by server slug, credential owner, and effective registry fingerprint. Global servers use one global owner key; person-bound servers use the canonical person slug resolved from verified caller identity. The lease remains warm while calls from that owner arrive and expires after its idle TTL.

- Tool catalogs are cached per lease after `tools/list`. The cache is invalidated when the server emits `tools/list_changed`, the effective MCP configuration changes, the environment fingerprint changes, or the lease restarts.
- Calls for a single server are serialized unless that server is explicitly marked parallel-safe. Shared leases preserve response routing by MCP request id, cancellation token, caller timeout, and operation trace.
- A failure in one call does not prevent later queued calls from using the lease unless the lease itself fails.
- Stdio responses are read with a bounded daemon-owned stream limit large enough for known tool catalogs. Malformed or over-limit stdout fails the active request instead of leaving it pending.
- Stdio, Streamable HTTP, and remote-proxy MCP servers share the same CLI/API surface. The runtime hides transport differences behind the lease.

### Registry shape

- `teleclaude-mcp.jsonc` is the committed shared registry. `teleclaude-mcp.local.jsonc` is the gitignored machine-local overlay.
- Registry files use JSONC and a TeleClaude-owned wrapper shape with top-level `servers`. They are not native Claude, Codex, Gemini, or Antigravity MCP config files.
- The JSON Schema is available locally so editors can validate and complete registry properties without internet access. Committed registry files use a portable relative schema reference; generated machine-local examples may use an absolute `file://` reference to the installed schema.

- Optional runtime behavior is defaulted by the runtime model and schema, not copied into every server entry. Defaults are: lazy enabled, serialized per-server calls, and 15 minute idle TTL. MCP operation budgets are fixed daemon defaults, not per-server or per-tool registry options: 10 second startup, 5 second `tools/list`, and 10 second `tools/call`.
- When an idle lease expires, the runtime closes its stdio process or remote session and removes the lease.

- Server definitions may declare stdio commands or remote HTTP/SSE endpoints. Environment placeholders are retained as placeholders in the registry and resolved only at lease start.

- Server definitions may declare a top-level `trigger` string. The trigger is human-facing discovery metadata only: it is advertised by `telec mcp list` and does not affect startup, credential lookup, or lease fingerprinting.

- Server definitions may declare `credentialScope` as `global` or `person`. The default is `global`, preserving existing registries and shared lease behavior. `person` requires a verified human caller that resolves to a configured person and makes every environment placeholder on that server a requirement of that person's secret store.
- Credential scope is runtime policy, not agent input. The `/mcp` edge translates verified caller identity into typed invocation context; tool arguments never select or override the credential owner.

- The effective registry is resolved per invocation project. A TeleClaude project's own `teleclaude-mcp.jsonc` and `teleclaude-mcp.local.jsonc` at its checkout root are deep-merged over the machine-wide TeleClaude registry, with project definitions taking precedence over machine-wide definitions and the local overlay taking precedence over the shared file within each root. Invocations from a project subdirectory or a todo worktree resolve the owning project checkout's registry. Invocations from outside any TeleClaude project keep their current per-subcommand behavior.
- The daemon keys runtimes, leases, and fingerprints per resolved project root. A lease never serves a differing definition from another root; the existing drift and fingerprint rules apply within each root. Environment placeholders on project declarations resolve exactly as machine-wide ones do — from the TeleClaude environment at lease start, never through agent sessions and never into any file.
- Project declarations use the same wrapper shape and schema as the machine-wide registry.
- Publication bakes a project MCP server index — the project's own declarations with their activation triggers — into that project's generated agent entrypoint files, parallel to the machine-wide baked index. A project with no registry declarations gets no such section and is untouched.
- Server definitions in either registry may declare `hidden: true` (default `false`). A hidden server is excluded from the baked agent-entrypoint indexes — machine-wide and project alike — while remaining fully served and listed by the runtime `telec mcp list` surface.

### Use cases

#### UC-LMCP-1: A person discovers configured services without starting them

```gherkin
Scenario: Discover the configured services without starting them
  Given a person asks their assistant which MCP services are configured
  When the assistant lists them with one service excluded
  Then the list contains the remaining services and their activation triggers
  And it omits the excluded service without starting any server
  And the response exposes no resolved secret values
```

#### UC-LMCP-2: A person can discover tools from their own MCP server

```gherkin
Scenario: Discover tools from the person's own server
  Given a person has configured a personal MCP server and stored its required secret
  When their assistant asks for that server's tools
  Then the server starts with that person's secret and no other person's credentials
  And the assistant receives the server's advertised tools
```

#### UC-LMCP-3: A person can use an advertised tool through their assistant

```gherkin
Scenario: Use a tool discovered for the person's server
  Given a person asks their assistant to use an advertised personal-server tool
  When the assistant invokes that tool
  Then the result returns to the assistant through the person's own server
  And no other person's server receives the call or result
```

#### UC-LMCP-4: Concurrent callers remain isolated

#### UC-LMCP-5: Idle leases close automatically

#### UC-LMCP-6: An operator's changes take effect on the next server use

```gherkin
Scenario: Use the updated server after its configuration changes
  Given an operator has changed a server definition or one of its environment values
  When an assistant next lists that server's tools or invokes one
  Then the updated server is used for that project and credential owner
  And the stale server session is no longer used
```

#### UC-LMCP-7: A person receives a safe refusal when their server secret is unavailable

```gherkin
Scenario: A person receives a safe refusal when their server secret is unavailable
  Given a person's configured MCP server needs a secret that their own secret store does not safely provide
  When their assistant asks to use that server
  Then the server is not started
  And the refusal names the missing requirement without exposing any secret or another person's identity
```

#### UC-LMCP-8: A developer validates MCP registry files offline

```
Given a developer opens `teleclaude-mcp.jsonc` or `teleclaude-mcp.local.jsonc`
When the editor resolves the registry schema without internet access

Then the editor validates the TeleClaude registry and offers completions for supported server settings
And committed registry files use a portable schema reference
And machine-local examples may use a local schema reference

```

#### UC-LMCP-9: Person-bound access requires authoritative human identity

#### UC-LMCP-10: Different people never share a personal lease

#### UC-LMCP-11: An operator makes a global service available to eligible callers

```gherkin
Scenario: An operator shares a global service across eligible callers
  Given an operator configures an MCP server with global credentials
  When eligible assistants use that server
  Then they use its global credential scope
  And its credentials come from the global TeleClaude environment
```

#### UC-LMCP-12: Rotating a personal secret invalidates only its owner lease

```gherkin
Scenario: Use the rotated secret on the person's next request
  Given two people use the same personal MCP server with separate secrets
  When one person rotates their secret and next uses the server
  Then only that person's server session is refreshed
  And the other person's and global server sessions remain available
```

#### UC-LMCP-13: An operator can configure a remote server with environment-backed credentials

```gherkin
Scenario: Use a remote service with environment-backed headers
  Given an operator has configured a remote MCP server with headers that refer to available environment secrets
  When their assistant lists the server's tools
  Then the remote server starts and returns its advertised tools
  And resolved header values are supplied to the local proxy process through its environment and sent to the remote server as headers, not as process arguments
  And server-provided tool metadata and results are returned unchanged rather than secret-redacted
```

#### UC-LMCP-14: An operator can inspect configured services while the daemon is unavailable

```gherkin
Scenario: Discover configured services while the daemon is unavailable
  Given an operator needs to inspect the MCP services configured on their computer
  And the TeleClaude daemon is unavailable
  When their assistant lists configured servers
  Then the server names and activation triggers are still available
  And no MCP server is started
```

#### UC-LMCP-15: A project operator can declare a service for that project

```gherkin
Scenario: Make a project service available only to that project
  Given a project operator declares an MCP service for their project
  When agents discover configured services from that project
  Then they see the project service alongside machine-wide services
  And agents in other projects do not see that project-only service
```

#### UC-LMCP-16: A project operator can override a machine service for that project

```gherkin
Scenario: Override a machine service for one project
  Given the same MCP service has a machine-wide definition and a project-specific definition
  When an agent uses that service from the project
  Then it uses the project's effective definition
  And other projects continue to use their own effective definitions
```

#### UC-LMCP-17: Leases from different projects never collide

```
Given two TeleClaude projects declare differing definitions for the same server slug
When agents in each project call tools on that slug
Then each caller reaches a server started from its own project-effective definition
And a lease started for one project's definition is never reused for the other
```

#### UC-LMCP-18: A project agent uses the same service from any project location

```gherkin
Scenario: Use project services from any working location in the project
  Given a project configures an MCP service for its agents
  When an agent working for that project uses the service from a subdirectory or its worktree
  Then it reaches the same project service it would from the project root
```

#### UC-LMCP-19: A project operator makes declared services discoverable to agents

```gherkin
Scenario: Help project agents discover their configured services
  Given a project operator declares MCP services for the project
  When the project's agent instructions are published
  Then project agents can see the declared services and their activation triggers
  And machine-wide service discovery remains available
  And a project with no services gets no empty project service list
```

#### UC-LMCP-21: An operator hides a service from the default overview but keeps it available

```gherkin
Scenario: Keep a service out of default discovery without disabling it
  Given an operator wants an MCP service hidden from the default agent list
  When agents are given their service overview or explicitly ask to list servers
  Then the service is absent from the default overview
  And it remains available for explicit listing, tool discovery, and calls
```

## Known caveats

- MCP tool catalogs and call results are returned as the server supplies them. If a server includes text matching one of its configured secrets, that text may reach the agent; the runtime does not redact server-controlled content.
- Stdio MCP servers cannot be attached to directly after startup. The daemon must broker every interaction because it owns the only stdin/stdout channel.
- Parallel tool calls are not assumed safe. Serialization is the default until a server is explicitly configured as parallel-safe.
- Specialized procedures can exclude their server from generic discovery while still using the same runtime underneath.

- Compatibility import support for `mcp.json` and `mcp.local.json` preserves migration input compatibility only.
