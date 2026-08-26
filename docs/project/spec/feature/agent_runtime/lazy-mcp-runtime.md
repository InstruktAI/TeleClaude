---
description: Daemon-owned lazy MCP runtime for on-demand server discovery, tool listing,
  and tool calls through the telec mcp surface.
visibility: public
---

# Lazy MCP Runtime — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

Lazy MCP runtime gives agents access to configured MCP servers without loading every server into every agent process at startup. The TeleClaude daemon owns MCP server leases, starts or connects to a server only when a caller asks for its tools or invokes a tool, and exposes the capability through `telec mcp` and `/mcp` API endpoints.

<!-- planned-change:person-scoped-mcp-credentials -->

The TeleClaude MCP registry is the source of available servers. Server entries from `teleclaude-mcp.jsonc` and `teleclaude-mcp.local.jsonc` are accumulated into the daemon's effective MCP catalog; those source files are inputs, not mutation targets. `mcp.json` and `mcp.local.json` are compatibility import inputs during the transition window only. Secret placeholders in server definitions resolve from the TeleClaude environment file at runtime, and resolved secret values never appear in agent-facing output.
<!-- change:person-scoped-mcp-credentials -->

The TeleClaude MCP registry is the source of available servers. Server entries from `teleclaude-mcp.jsonc` and `teleclaude-mcp.local.jsonc` are accumulated into the daemon's effective MCP catalog; those source files are inputs, not mutation targets. `mcp.json` and `mcp.local.json` are compatibility import inputs during the transition window only. Each server declares whether its credential owner is global or the verified person behind the caller. Secret placeholders resolve exclusively from that owner's TeleClaude environment file at lease start, and resolved secret values never appear in agent-facing output.
<!-- /planned-change:person-scoped-mcp-credentials -->

## Canonical fields

### API surface

- `GET /mcp/servers` — returns the configured MCP server catalog with secret-safe launch metadata and activation triggers.
- `GET /mcp/servers/{slug}/tools` — lazy-initializes the server lease when needed, calls `tools/list`, caches the tool catalog, and returns it.
- `POST /mcp/servers/{slug}/tools/{tool}/call` — lazy-initializes the server lease when needed, sends `tools/call` with the supplied JSON arguments, and returns the tool result.

### CLI surface

- `telec mcp list [--exclude <slug> ...]` — prints configured server slugs with activation triggers.
- `telec mcp list-tools <slug>` — prints the server's current tool catalog, initializing the daemon-owned lease on first use.
- `telec mcp call <slug> <tool> --json '<arguments>'` — invokes one tool through the daemon-owned lease and returns the MCP tool result.

### Runtime ownership

- The daemon owns stdio child processes and remote MCP sessions. Agents never receive raw stdio pipes, session identifiers, or secret-expanded launch commands.
- Managed MCP servers use the lazy runtime by default and are not published into native agent MCP configs unless a per-server compatibility opt-in enables native publication.

<!-- planned-change:person-scoped-mcp-credentials -->

- A lease is keyed by server slug and effective registry fingerprint. The lease remains warm while calls arrive and expires after its idle TTL.

<!-- change:person-scoped-mcp-credentials -->

- A lease is keyed by server slug, credential owner, and effective registry fingerprint. Global servers use one global owner key; person-bound servers use the canonical person slug resolved from verified caller identity. The lease remains warm while calls from that owner arrive and expires after its idle TTL.

<!-- /planned-change:person-scoped-mcp-credentials -->

- Tool catalogs are cached per lease after `tools/list`. The cache is invalidated when the server emits `tools/list_changed`, the effective MCP configuration changes, the environment fingerprint changes, or the lease restarts.
- Calls for a single server are serialized unless that server is explicitly marked parallel-safe. Shared leases preserve response routing by MCP request id, cancellation token, caller timeout, and operation trace.
- Stdio responses are read with a bounded daemon-owned stream limit large enough for known tool catalogs. Malformed or over-limit stdout fails the active request instead of leaving it pending.
- Stdio, Streamable HTTP, and remote-proxy MCP servers share the same CLI/API surface. The runtime hides transport differences behind the lease.

### Registry shape

- `teleclaude-mcp.jsonc` is the committed shared registry. `teleclaude-mcp.local.jsonc` is the gitignored machine-local overlay.
- Registry files use JSONC and a TeleClaude-owned wrapper shape with top-level `servers`. They are not native Claude, Codex, Gemini, or Antigravity MCP config files.
- The JSON Schema is available locally so editors can validate and complete registry properties without internet access. Committed registry files use a portable relative schema reference; generated machine-local examples may use an absolute `file://` reference to the installed schema.
- Optional runtime behavior is defaulted by the runtime model and schema, not copied into every server entry. Defaults are: lazy enabled, native publication disabled, serialized per-server calls, and 15 minute idle TTL. MCP operation budgets are fixed daemon defaults, not per-server or per-tool registry options: 10 second startup, 5 second `tools/list`, and 10 second `tools/call`.
- Server definitions may declare stdio commands or remote HTTP/SSE endpoints. Environment placeholders are retained as placeholders in the registry and resolved only at lease start.
- Server definitions may declare a top-level `trigger` string. The trigger is human-facing discovery metadata only: it is advertised by `telec mcp list` and does not affect startup, credential lookup, native publication, or lease fingerprinting.

<!-- planned:person-scoped-mcp-credentials -->

- Server definitions may declare `credentialScope` as `global` or `person`. The default is `global`, preserving existing registries and shared lease behavior. `person` requires a verified human caller that resolves to a configured person and makes every environment placeholder on that server a requirement of that person's secret store.
- Credential scope is runtime policy, not agent input. The `/mcp` edge translates verified caller identity into typed invocation context; tool arguments never select or override the credential owner.

<!-- /planned:person-scoped-mcp-credentials -->

<!-- planned:per-project-mcp-registry -->

- A TeleClaude project's own `teleclaude-mcp.jsonc` and `teleclaude-mcp.local.jsonc` at its checkout root declare project-local MCP servers, using the same wrapper shape as the machine-wide registry with the local overlay deep-merged over the shared file. A project declaration carries the server-launch contract: transport, command, arguments, URL, headers, environment references, and enabled state. Fields whose meaning binds to the machine-wide daemon runtime — the native-publication opt-in, lazy-lease tuning, and catalog trigger metadata — are invalid in a project registry and rejected with an error naming the server and the field. Project declarations are generation inputs for agent-native project-local MCP configs; they do not enter the daemon's effective registry, the `telec mcp` surface, or user-home native agent configs. The machine-wide TeleClaude registry remains the only global authority.
- Generation writes, for every enabled project declaration, the project-scoped native config artifact of each supported agent CLI that has both a documented project-scoped MCP surface and secret-free credential semantics; a CLI lacking either is not served, and the generation result names the gap. Environment references are preserved as placeholders or by-name references per the target CLI's contract; no resolved secret value is ever written to a generated file. Each CLI's own trust and approval gates govern activation.
- Generated native configs are machine-local artifacts, never committed. Project plumbing establishes the boundary: the blessed ignore patterns cover the local overlay registry and every managed native target, applied at project initialization and sync. The platform regenerates the artifacts at initialization and sync and provisions them into todo worktrees, so worktree sessions observe the same project servers as checkout sessions. Because outputs stay machine-local, the local overlay participates in generation without entering version control.
- A native target file already tracked by the project's repository is treated as wholly hand-authored: generation never writes to it, the project's declarations are not published for that CLI, and the generation result names the tracked target as the gap.
- Generation merges non-destructively with hand-authored content in the target files and adds, updates, or removes only the entries it manages. A registry declaration whose identifier collides with a hand-authored entry is never silently resolved: the hand-authored entry is preserved unchanged, the declaration is not published into that file, and the generation result names the collision. The compat registry input filename (`mcp.json`) is never a generation target.

<!-- /planned:per-project-mcp-registry -->

### Use cases

#### UC-LMCP-1: List configured servers without starting them

```
Given the effective TeleClaude MCP registry contains `firecrawl`, `omi-memory`, and `context7`
When an agent runs `telec mcp list --exclude firecrawl`
Then the response lists `omi-memory` and `context7` with their activation triggers
And the response omits `firecrawl`
And no MCP server process or remote MCP session is started
And the human-readable output does not expose transport or environment metadata
And the response never includes resolved environment secret values
```

<!-- planned-change:person-scoped-mcp-credentials -->

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

<!-- change:person-scoped-mcp-credentials -->

#### UC-LMCP-2: Listing tools lazily initializes one person-bound server

```
Given no lease is active for `omi-memory` for person `maurice-faber`
And `omi-memory` has credential scope `person`
And its effective definition requires `OMI_API_KEY`
And the verified caller resolves to person `maurice-faber`
And that person's secret store contains `OMI_API_KEY`
When the caller runs `telec mcp list-tools omi-memory`
Then the daemon resolves `OMI_API_KEY` only from that person's secret store
And starts or connects to only the `omi-memory` lease owned by that person
And completes MCP initialization
And sends `tools/list`
And returns the advertised tools
And stores the lease and tool catalog for later callers owned by the same person
```

<!-- /planned-change:person-scoped-mcp-credentials -->

<!-- planned-change:person-scoped-mcp-credentials -->

#### UC-LMCP-3: Calling a tool reuses the warm lease

```
Given a warm lease exists for `omi-memory`
And the cached catalog includes `search_memories`
When an agent runs `telec mcp call omi-memory search_memories --json '{"query":"deployment notes"}'`
Then the daemon sends a `tools/call` request over the existing lease
And returns the MCP tool result as JSON
And refreshes the lease idle deadline
```

<!-- change:person-scoped-mcp-credentials -->

#### UC-LMCP-3: Calling a tool reuses the warm lease for its credential owner

```
Given a warm `omi-memory` lease exists for the verified caller's person
And the cached catalog includes `search_memories`
When another agent rooted in that same person runs `telec mcp call omi-memory search_memories --json '{"query":"deployment notes"}'`
Then the daemon sends `tools/call` over that person's existing lease
And returns the MCP tool result as JSON
And refreshes only that lease's idle deadline
```

<!-- /planned-change:person-scoped-mcp-credentials -->

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
And the effective `teleclaude-mcp.jsonc` plus `teleclaude-mcp.local.jsonc` registry changes
When an agent next lists tools or calls a tool for `firecrawl`
Then the daemon compares the lease fingerprint with the effective fingerprint
And closes the stale lease
And starts a fresh lease from the new effective definition
```

<!-- planned-change:person-scoped-mcp-credentials -->

#### UC-LMCP-7: Missing credentials fail secret-safe

```
Given a server definition references `${OMI_API_KEY}`
And the TeleClaude environment file does not contain `OMI_API_KEY`
When an agent runs `telec mcp list-tools omi-memory`
Then the command fails before starting the server
And the error names the missing environment variable
And the error does not print command lines containing resolved secrets
```

<!-- change:person-scoped-mcp-credentials -->

#### UC-LMCP-7: Missing owner credentials fail secret-safe

```
Given a person-bound server definition references `${OMI_API_KEY}`
And the verified caller resolves to a configured person
And that person's secret store is absent, unsafe, or does not contain a non-empty `OMI_API_KEY`
When the caller runs `telec mcp list-tools omi-memory`
Then the command fails before starting the server
And the runtime does not consult the global environment or another person's secret store
And the error names the unmet requirement without exposing a secret value or another person's identity
```

<!-- /planned-change:person-scoped-mcp-credentials -->

#### UC-LMCP-8: Registry schema supports offline editor validation

```
Given a developer opens `teleclaude-mcp.jsonc` or `teleclaude-mcp.local.jsonc`
When the editor resolves the registry schema without internet access
Then the editor validates the TeleClaude wrapper shape
And offers completions for server transport, lazy runtime defaults, native-publication opt-in, headers, args, and env placeholders
And committed registry files use a portable schema reference
And machine-local generated examples may use an absolute file schema reference
```

<!-- planned:person-scoped-mcp-credentials -->

#### UC-LMCP-9: Person-bound access requires authoritative human identity

```
Given `omi-memory` has credential scope `person`
And the caller is system-only, anonymous, or cannot resolve to a configured person
When the caller lists tools or invokes a tool on `omi-memory`
Then the operation is denied before credential lookup and lease creation
And a client-writable identity marker or tool argument cannot supply the missing person
```

#### UC-LMCP-10: Different people never share a personal lease

```
Given person A and person B each have an `OMI_API_KEY`
And person A has a warm `omi-memory` lease
When an agent rooted in person B invokes `omi-memory`
Then the daemon creates or reuses only person B's lease
And person A's process, remote session, credentials, tool catalog, and response stream remain inaccessible
```

#### UC-LMCP-11: Global servers remain shared

```
Given `firecrawl` omits `credentialScope`
And two verified callers belong to different people
When both callers use `firecrawl`
Then the registry default resolves the server as globally scoped
And both callers reuse the eligible global lease
And credentials continue to resolve from the global TeleClaude environment
```

#### UC-LMCP-12: Rotating a personal secret invalidates only its owner lease

```
Given two people have warm leases for the same person-bound MCP server
When one person's required secret changes
And that person next lists tools or invokes a tool
Then the runtime closes and replaces only that person's stale lease
And the other person's lease and every global lease remain active
```

<!-- /planned:person-scoped-mcp-credentials -->

#### UC-LMCP-13: Present header credentials start the remote server secret-safe

```
Given a remote MCP server definition declares header values referencing environment variables in any registry-accepted placeholder form (`${VAR}`, `${VAR:-fallback}`, or bare `$VAR`)
And the TeleClaude environment file contains every referenced variable
When an agent runs `telec mcp list-tools` for that server
Then the daemon starts the remote proxy and returns the tool catalog
And every header reference reaches the proxy command line normalized to the simple braced placeholder form the proxy substitutes
And no resolved secret appears in the proxy command line
And each referenced secret reaches the proxy only through its process environment
```

#### UC-LMCP-14: Listing configured servers succeeds while the daemon is down

```
Given the daemon API socket is unavailable
When an agent runs `telec mcp list`
Then the configured server slugs and their activation triggers are listed from the effective registry
And the command exits successfully without contacting the daemon
```

<!-- planned:per-project-mcp-registry -->

#### UC-LMCP-15: Project declarations reach the project's Claude Code sessions

```
Given a TeleClaude project declares an enabled MCP server in its own registry
When project native MCP configs are generated
Then the project root carries a Claude Code project MCP config advertising the server
And every environment reference in it remains a placeholder
And a Claude Code session in that project can use the server after that CLI's own trust approvals
And sessions in other projects observe nothing
```

#### UC-LMCP-16: Project declarations reach the project's Codex sessions

```
Given a TeleClaude project declares an enabled MCP server in its own registry
When project native MCP configs are generated
Then the project's Codex project config declares the server with credentials referenced by environment-variable name
And a Codex session in that trusted project can use the server
And no resolved secret value appears in the generated file
```

#### UC-LMCP-17: Generation preserves hand-authored native config content

```
Given a project's native MCP config artifact carries hand-authored entries or unrelated settings
When project native MCP configs are regenerated
Then the hand-authored content is preserved
And only entries managed by the generator are added, updated, or removed
```

#### UC-LMCP-18: CLIs without a safe project surface are not served

```
Given a supported agent CLI lacks a documented project-scoped MCP surface or secret-free credential semantics
When project native MCP configs are generated
Then no artifact is generated for that CLI
And no project declaration reaches any user-home native agent config
And the generation result names the unserved CLI
```

#### UC-LMCP-19: Machine-wide surfaces are unaffected by project declarations

```
Given a TeleClaude project declares MCP servers in its own registry
When an agent runs `telec mcp list` from anywhere
Then the listing reflects only the machine-wide TeleClaude registry
And user-home native agent configs remain exactly the machine-wide publication result
```

#### UC-LMCP-20: Todo worktrees inherit the project's native MCP configs

```
Given a TeleClaude project with generated native MCP configs
When a todo worktree is created from that project
Then the worktree carries the same generated native MCP configs
And agent CLI sessions in the worktree observe the same project MCP servers as sessions in the checkout
```

#### UC-LMCP-21: Same-name collisions with hand-authored entries are refused visibly

```
Given a project's native MCP config carries a hand-authored server entry
And the project registry declares a server with the same identifier
When project native MCP configs are regenerated
Then the hand-authored entry is preserved unchanged
And the registry declaration is not published into that file
And the generation result names the collision
```

#### UC-LMCP-22: Tracked native targets are never modified

```
Given a project tracks a native MCP config target in its repository
When project native MCP configs are generated
Then the tracked file is not modified
And the project's declarations are not published for that CLI
And the generation result names the tracked target as the reason
```

#### UC-LMCP-23: Machine-wide-runtime fields are rejected in project registries

```
Given a project registry declares a server carrying a machine-wide-runtime-only field
When project native MCP configs are generated
Then generation reports an error naming the server and the invalid field
And that declaration reaches no native config
```

<!-- /planned:per-project-mcp-registry -->

## Known caveats

- Stdio MCP servers cannot be attached to directly after startup. The daemon must broker every interaction because it owns the only stdin/stdout channel.
- Parallel tool calls are not assumed safe. Serialization is the default until a server is explicitly configured as parallel-safe.
- Specialized procedures can exclude their server from generic discovery while still using the same runtime underneath.
- Compatibility import support for `mcp.json` and `mcp.local.json` preserves migration input compatibility only; native agent MCP publication remains off by default for managed servers.
