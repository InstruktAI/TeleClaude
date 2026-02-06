---
description: 'Security policy for AI agent systems covering prompt injection, credential isolation, skill trust, session boundaries, network exposure, and supply chain risks. Informed by real-world incidents in open-source agentic platforms.'
id: 'software-development/policy/ai-agent-security'
scope: 'domain'
type: 'policy'
---

# AI Agent Security — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/security-awareness.md

## Rules

### Fundamental tension

A useful agent requires broad permissions — file access, shell execution, credential
use, network communication. Broad permissions create a massive attack surface. Every
architectural decision must navigate this tension explicitly. Do not pretend it can
be eliminated; manage it through layered controls.

### Prompt injection defense

LLMs cannot reliably distinguish instructions from content. All external content
ingested by an agent — emails, messages, webhook payloads, web pages, file contents —
must be treated as potentially adversarial.

- Never pass raw external content as system-level instructions to the agent.
- Separate the instruction channel from the data channel at the architecture level.
- Validate and sanitize agent outputs before executing privileged operations
  (shell commands, file writes, credential access).
- Log all tool invocations with full parameters for post-incident analysis.
- When an agent processes user-supplied content, apply output filtering to detect
  attempts to exfiltrate credentials or execute unintended commands.

### Credential isolation

API keys, tokens, and secrets must never appear in agent conversation context,
tool call parameters visible to other sessions, or log output.

- Store credentials in environment variables or secret managers, never in config
  files that agents can read as context.
- Scope credentials per integration — a Telegram bot token should not grant
  access to email credentials.
- Rotate credentials on a regular schedule and immediately after any suspected
  exposure.
- Agent sessions must not be able to read credentials belonging to other sessions.
- Never store credentials in plaintext alongside agent configuration. An info
  stealer with filesystem access should not find API keys in predictable locations.

### Session isolation

Agent sessions must be isolated from each other to prevent cross-session
contamination, privilege escalation, and data leakage.

- Inject session identifiers at the transport layer (not from agent-controlled input).
- Restrict tool access based on the session's assigned role — worker sessions
  must not access orchestration tools.
- Use filesystem permissions and per-session temporary directories to prevent
  one session from reading another's state.
- Session IDs must be opaque and unguessable; never derive them from
  user-controlled input.

### Skill and plugin trust

Skills are code that runs with the full permissions of the agent process.
There is no sandbox. Treat skill installation as equivalent to granting
root access.

- All skills must be code-reviewed before deployment. No auto-trust of
  downloaded or marketplace-sourced code.
- Skills must declare their required capabilities (filesystem, network, shell)
  in their metadata.
- Do not inflate or trust download counts, star counts, or popularity metrics
  as indicators of safety.
- The distribution pipeline must only deploy skills from the controlled source
  repository — never from unvetted external sources.
- Monitor skills for unexpected behavior: network connections to unknown hosts,
  credential file access, or shell command execution outside their declared scope.

### Network boundary security

Exposing an agent gateway to the network — even on localhost — creates an
attack surface. Reverse proxies, tunnels, and load balancers can silently
change the trust properties of connections.

- Never trust connections based solely on source IP (localhost). A reverse proxy
  forwards external traffic as localhost by default.
- Use Unix domain sockets with filesystem permissions for local IPC instead of
  TCP ports where possible.
- If TCP is required, require explicit authentication on every connection
  regardless of source address.
- When using tunnels (Cloudflare, ngrok, etc.) to expose local services,
  understand that you are punching a hole through your network perimeter.
  Apply authentication and rate limiting at the tunnel ingress.
- TLS is mandatory for any connection that leaves the local machine. For
  self-signed certificates in internal transport, pin the certificate rather
  than disabling verification entirely.
- Audit exposed ports and services regularly. A scan of your own infrastructure
  should find zero unintended open services.

### Role-based tool filtering

Agents operating in different roles (orchestrator, worker, builder) must have
access only to the tools required for their role.

- Enforce tool filtering at both the tool listing phase and the tool execution
  phase — do not rely on the agent to self-restrict.
- Worker agents must not have access to session management, deployment, or
  orchestration tools.
- Role markers must be set by the infrastructure (wrapper, daemon), not by
  the agent itself.

### Supply chain security for agent ecosystems

The agent's dependency chain extends beyond traditional software dependencies
to include skills, model providers, and communication adapters.

- Pin dependencies with checksums. Monitor for CVEs.
- Vet model provider API endpoints — ensure HTTPS, certificate validation,
  and that responses are not being intercepted.
- Communication adapters (Telegram, messaging platforms) are trust boundaries.
  Messages from these channels are user input, not trusted instructions.
- When rebranding, rotating credentials, or changing account handles, secure
  the new identifiers before releasing the old ones. A 10-second gap is
  enough for attackers to hijack accounts.

## Rationale

These rules are informed by real-world incidents in open-source agentic AI
platforms (2026), including: authentication bypass via reverse proxy localhost
trust, prompt injection via email leading to credential exfiltration in under
5 minutes, unmoderated skill marketplaces enabling supply chain attacks, and
account hijacking during rebranding operations. The fundamental architectural
tension — useful agents require broad permissions, broad permissions create
massive attack surfaces — cannot be resolved, only managed through defense
in depth.

## Scope

Applies to all AI agent systems, whether local-first or cloud-hosted, in
this project and any project that deploys autonomous agents with tool access.

## Enforcement

- Code review must verify credential isolation before merge.
- Session isolation must be tested as part of the integration test suite.
- Network exposure must be audited after any change to transport or proxy configuration.
- Skill deployment must go through the controlled distribution pipeline.
- Prompt injection mitigations must be documented for any new external data ingestion path.

## Exceptions

None.
