---
visibility: internal
number: 93
date: 2026-09-19
description: Bind personal MCP credentials and reusable client state to TeleClaude's verified person identity.
---

# Bind MCP Credentials to the Verified Owner — ADR

## Context

TeleClaude hosts MCP clients and reuses their connections. That shared host
model is appropriate for globally configured services, but a provider such as
Omi exposes one person's private data through a bearer credential. A server
slug alone therefore cannot identify a reusable client safely once two people
can invoke the same person-bound service.

The MCP architecture assigns authorization, client lifecycle, and isolation to
the host. Its official TypeScript SDK keeps credential storage behind a client
provider, binds stored credentials to the authorization-server issuer, and
supplies tokens at the transport boundary. Its official Go SDK binds server
sessions to verified token user identity. VS Code provides a production host
analogue that stores sensitive MCP inputs outside server configuration and
injects them when the server starts. Omi supports a person-held MCP bearer key
for both hosted and local client configurations.

## Decision

Adapt the existing TeleClaude MCP host. A server declaration selects either the
global credential owner or the verified person behind the caller. Personal
credentials resolve only through the config-owned store for that person, and
the same owner identity participates in lease selection, fingerprints, cached
capabilities, and tool traffic. Missing or ambiguous person ownership fails
before credential lookup or server startup. Do not add a second credential
broker or require provider OAuth for a service configured with a static bearer
key.

## Consequences

- Existing global services retain their shared lease and secret source.
- Two callers may reuse a personal lease only when both resolve to the same
  canonical person.
- Credential rotation invalidates only the affected owner's reusable client
  state.
- API edges must translate verified caller identity into an owner-bearing
  invocation context before entering the runtime.
- Config becomes the sole owner of personal secret persistence and safe
  retrieval; runtime and UI code cannot read the store directly.
- Static personal keys remain machine-local operator-managed secrets. Providers
  that require interactive OAuth need a separate credential-acquisition flow,
  but they use the same credential-owner and lease-isolation boundary.

## Alternatives Considered

### One shared credential and lease per server

Rejected because one person's bearer credential and returned data could be
reused for another caller.

### A separate MCP credential-broker service

Rejected because the existing identity, config, and runtime contexts already
own the required decisions and state. Another service would duplicate those
owners without adding an external trust boundary.

### Require OAuth for every person-bound service

Rejected because providers may expose operator-provisioned static MCP keys and
the host still needs owner-scoped storage and client isolation for those keys.

## See Also

- https://modelcontextprotocol.io/specification/2025-03-26/architecture/index
- https://apps.extensions.modelcontextprotocol.io/api/documents/authorization.html
- https://docs.omi.me/doc/developer/mcp/setup
- https://code.visualstudio.com/docs/agents/reference/mcp-configuration
- https://github.com/modelcontextprotocol/typescript-sdk/blob/main/packages/client/src/client/auth.ts
- https://github.com/modelcontextprotocol/go-sdk/blob/main/mcp/streamable.go
