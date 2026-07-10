---
description: 'Daemon-owned lazy MCP runtime for on-demand server discovery, tool listing, and tool calls through the telec mcp surface.'
delivered_by:
  - api-service-to-lazy-load-mcp-features
visibility: 'public'
---

# Lazy MCP Runtime — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

Lazy MCP runtime gives agents access to configured MCP servers without loading every server into every agent process at startup. The TeleClaude daemon owns MCP server leases, starts or connects to a server only when a caller asks for its tools or invokes a tool, and exposes the capability through `telec mcp` and `/mcp` API endpoints.

The merged MCP registry is the source of available servers. Server entries from `mcp.json` and `mcp.local.json` are accumulated into the daemon's effective MCP catalog; those source files are inputs, not mutation targets. Secret placeholders in server definitions resolve from the TeleClaude environment file at runtime, and resolved secret values never appear in agent-facing output.

## Canonical fields

### API surface

- `GET /mcp/servers` — returns the configured MCP server catalog with secret-safe launch metadata and usage instructions.
- `GET /mcp/servers/{slug}/tools` — lazy-initializes the server lease when needed, calls `tools/list`, caches the tool catalog, and returns it.
- `POST /mcp/servers/{slug}/tools/{tool}/call` — lazy-initializes the server lease when needed, sends `tools/call` with the supplied JSON arguments, and returns the tool result.

### CLI surface

- `telec mcp list [--exclude <slug> ...]` — prints configured server slugs and the next commands an agent should run.
- `telec mcp list-tools <slug>` — prints the server's current tool catalog, initializing the daemon-owned lease on first use.
- `telec mcp call <slug> <tool> --json '<arguments>'` — invokes one tool through the daemon-owned lease and returns the MCP tool result.

### Runtime ownership

- The daemon owns stdio child processes and remote MCP sessions. Agents never receive raw stdio pipes, session identifiers, or secret-expanded launch commands.
- A lease is keyed by server slug and effective configuration fingerprint. The lease remains warm while calls arrive and expires after its idle TTL.
- Tool catalogs are cached per lease after `tools/list`. The cache is invalidated when the server emits `tools/list_changed`, the effective MCP configuration changes, the environment fingerprint changes, or the lease restarts.
- Calls for a single server are serialized unless that server is explicitly marked parallel-safe. Shared leases preserve response routing by MCP request id, cancellation token, caller timeout, and operation trace.
- Stdio, Streamable HTTP, and remote-proxy MCP servers share the same CLI/API surface. The runtime hides transport differences behind the lease.

### Use cases

#### UC-LMCP-1: List configured servers without starting them

```
Given the effective MCP registry contains `firecrawl`, `omi-memory`, and `context7`
When an agent runs `telec mcp list --exclude firecrawl`
Then the response lists `omi-memory` and `context7`
And the response omits `firecrawl`
And no MCP server process or remote MCP session is started
And the response includes the exact `telec mcp list-tools <slug>` and `telec mcp call <slug> <tool>` forms to use next
And the response never includes resolved environment secret values
```

#### UC-LMCP-2: Listing tools lazily initializes one server

```
Given no lease is active for `omi-memory`
And the effective server definition requires `OMI_API_KEY`
And the TeleClaude environment file contains `OMI_API_KEY`
When an agent runs `telec mcp list-tools omi-memory`
Then the daemon resolves `OMI_API_KEY` from the TeleClaude environment
And starts or connects to only the `omi-memory` MCP server
And completes MCP initialization
And sends `tools/list`
And returns the advertised tools
And stores the lease and tool catalog for later callers
```

#### UC-LMCP-3: Calling a tool reuses the warm lease

```
Given a warm lease exists for `omi-memory`
And the cached catalog includes `search_memories`
When an agent runs `telec mcp call omi-memory search_memories --json '{"query":"deployment notes"}'`
Then the daemon sends a `tools/call` request over the existing lease
And returns the MCP tool result as JSON
And refreshes the lease idle deadline
```

#### UC-LMCP-4: Concurrent callers remain isolated

```
Given two agents call tools on the same MCP server at the same time
When the server is not marked parallel-safe
Then the daemon queues the calls for that server in arrival order
And each caller receives only its own response, progress, cancellation, timeout, and error state
And a failure in one call does not poison queued calls unless the server lease itself fails
```

#### UC-LMCP-5: Idle leases close automatically

```
Given a server lease has no active calls
And its idle TTL expires
When the runtime reaper evaluates leases
Then the daemon sends MCP shutdown when supported
And terminates the stdio child process or closes the remote HTTP session
And removes the lease from the active registry
And preserves no secret material in logs or cache entries
```

#### UC-LMCP-6: Config or environment drift invalidates stale leases

```
Given a warm lease exists for `firecrawl`
And the effective `mcp.json` plus `mcp.local.json` registry changes
When an agent next lists tools or calls a tool for `firecrawl`
Then the daemon compares the lease fingerprint with the effective fingerprint
And closes the stale lease
And starts a fresh lease from the new effective definition
```

#### UC-LMCP-7: Missing credentials fail secret-safe

```
Given a server definition references `${OMI_API_KEY}`
And the TeleClaude environment file does not contain `OMI_API_KEY`
When an agent runs `telec mcp list-tools omi-memory`
Then the command fails before starting the server
And the error names the missing environment variable
And the error does not print command lines containing resolved secrets
```

## Known caveats

- Stdio MCP servers cannot be attached to directly after startup. The daemon must broker every interaction because it owns the only stdin/stdout channel.
- Parallel tool calls are not assumed safe. Serialization is the default until a server is explicitly configured as parallel-safe.
- Specialized procedures can exclude their server from generic discovery while still using the same runtime underneath.
