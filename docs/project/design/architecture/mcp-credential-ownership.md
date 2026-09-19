---
description: Composition of verified person identity, personal secret ownership, and MCP runtime lease isolation.
delivered_by:
  - person-scoped-mcp-credentials
---

# MCP Credential Ownership — Design

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/domain/config.md
- @docs/project/spec/domain/agent_runtime.md
- @docs/project/spec/identity-and-auth.md
- @docs/project/spec/teleclaude-config.md
- @docs/project/spec/feature/agent_runtime/lazy-mcp-runtime.md
- @docs/project/spec/feature/config/schema-driven-config-tui.md

## Purpose

This design composes the identity, config, and agent-runtime contracts for MCP
services whose credentials and returned data belong to one person. Each
bounded context retains its own rule: identity resolves the person, config owns
the secret store, and agent runtime owns server leases and tool traffic. The
API edge translates between those contracts without becoming a policy owner.

### Current and intended state

The runtime pool already isolates MCP runtimes by invocation project, while
each runtime currently keys leases only by server slug and reads one global
environment file. Protected MCP routes already resolve `CallerIdentity` but do
not pass it downstream. Registry normalization already derives environment
requirements and fingerprints, and the config context already provides locked
atomic environment-file mutation that preserves unrelated lines.

The person-owner coordinate is added inside each project-scoped runtime. The
existing global path remains the default; a person-scoped declaration requires
a verified canonical person before secret resolution or lease lookup.

### Prior art and adopt-vs-build

The design adapts the existing host-managed runtime rather than adding a second
credential broker or requiring provider OAuth. MCP assigns connection
authorization, lifecycle, and isolation to the host; Omi exposes a scoped
developer API key as the credential used by its client; and VS Code provides a
production host precedent where sensitive MCP inputs are stored outside server
configuration and injected only when the server starts.

The official MCP TypeScript SDK is the reference implementation for the owner
binding. Its client auth provider owns credential storage, stamps and looks up
stored credentials by authorization-server issuer, and supplies the token to
the transport instead of exposing credential selection to tool arguments. The
official Go SDK applies the same isolation shape to connection lifecycle by
binding a session to verified token user identity and rejecting subsequent
requests whose identity differs. TeleClaude adapts those owner-keyed
credential and session boundaries to its existing verified person identity and
static provider-key store.

## Inputs/Outputs

Inputs are the verified caller identity, invocation project root, normalized
MCP server declaration, registry-derived environment requirements, and the
config-owned secret source selected by credential scope.

Outputs are a secret-safe server catalog, an owner-bound MCP lease and tool
catalog, caller-safe denial details, and masked personal-secret inventory for
the trusted local People surface. Resolved secret values cross only into MCP
child-process or remote-request construction.

## Invariants

- Identity is resolved once at the protected API edge. Downstream components
  receive a typed invocation context carrying either a canonical person slug or
  explicit absence; headers, client session files, and tool arguments never
  select the person.
- Config is the sole owner of personal secret-file paths, safety checks,
  inventory, reads, and mutation. Runtime and TUI consumers use its published
  operations and never parse the store directly.
- Agent runtime is the sole owner of credential scope, environment requirement
  resolution for one invocation, fingerprints, leases, and tool catalogs.
- Lease identity is the invocation project runtime plus server slug,
  credential owner, and effective fingerprint. The global owner remains shared;
  the person owner is the canonical person slug.
- A person-scoped declaration fails before server startup when identity,
  configured person, safe storage, or a required non-empty secret is absent.
  It never consults the global store or another person's store.
- Personal secret values are write-only on operator surfaces. Existing values
  are never rendered or loaded into edit buffers; inventory exposes only name,
  set state, and requiring server slugs.
- Keep performs no mutation. Replace and clear preserve every unrelated key and
  line in the selected person's store and leave every other owner untouched.
- The People TUI retains its trusted local machine and terminal boundary. This
  design introduces no TUI role gate and does not alter existing CLI people
  restrictions.

## Primary flows

### Person-bound tool use

The protected MCP route resolves the caller and builds an invocation context.
The project runtime loads the server declaration, resolves its credential
owner, asks config for the required values from that owner's store, and selects
the composite lease. A matching owner and fingerprint reuses the lease;
otherwise only that owner's stale lease is replaced.

### Global tool use

A server with global credential scope uses the existing global secret source
and global owner coordinate. Callers from different people continue to reuse
the same eligible global lease inside the same project runtime.

### Personal secret management

The People surface combines registry-derived requirements with stored key names
and renders secret-safe status. Keep exits without writing. Replace or clear
invokes the config-owned targeted mutation, then reloads status from persisted
state. No existing value is returned to the UI.

### Secret rotation

The next invocation after a personal secret changes produces a different
owner-specific fingerprint. Runtime closes and replaces only that person's
stale lease; leases owned by other people and the global owner remain active.

## Failure modes

- An unresolved, anonymous, or system-only caller requesting a person-scoped
  service is denied before secret lookup.
- An unknown person, unsafe secret file, missing key, or empty required value
  is reported as an unmet requirement without revealing values or foreign
  identity.
- A registry declaration with an unsupported credential scope, or a
  person-scoped declaration incompatible with another publication mode, fails
  validation before it reaches runtime.
- Failure to start, list, or call an MCP server closes only the affected owner
  lease and returns the existing caller-safe runtime error shape.
- Concurrent targeted secret mutations serialize on the store lock; a failed
  replacement leaves the prior file intact.

## See Also

- https://modelcontextprotocol.io/specification/2025-03-26/architecture/index
- https://apps.extensions.modelcontextprotocol.io/api/documents/authorization.html
- https://docs.omi.me/api-reference/api-keys/create-api-key
- https://code.visualstudio.com/docs/agents/reference/mcp-configuration
- https://code.visualstudio.com/docs/agents/run/security
- https://github.com/modelcontextprotocol/typescript-sdk/blob/main/packages/client/src/client/auth.ts
- https://github.com/modelcontextprotocol/go-sdk/blob/main/docs/protocol.md
