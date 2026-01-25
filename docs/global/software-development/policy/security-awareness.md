---
description:
  Secrets management, input validation, OWASP awareness, secure defaults.
  Never commit secrets, validate boundaries.
id: software-development/policy/security-awareness
scope: domain
type: policy
---

# Security Awareness — Policy

## Required reads

- @~/.teleclaude/docs/software-development/standards/code-quality.md

## Rule

Security is a baseline constraint. Treat inputs as untrusted, validate at boundaries, and protect secrets by default.

- Secrets never enter version control or logs.
- Validation happens at the boundary, not deep in the core.
- Defaults are safe; permissions are explicit.

Always escalate before:

- Changing authentication or authorization boundaries.
- Modifying encryption or credential handling.
- Exposing new external entry points.

- Do not log secrets, tokens, or raw payloads containing credentials.
- Sanitize user input and apply allowlists where feasible.
- Use least-privilege defaults for access controls and file permissions.
- Prefer proven libraries over custom security implementations.

## Rationale

- Security failures are costly and often irreversible; prevention is cheaper than remediation.
- Clear guardrails reduce accidental exposure and privilege escalation.

## Scope

- Applies to all code paths that handle user input, credentials, or external integrations.

## Enforcement

- Security-sensitive changes require explicit review and documented approvals.
- Automated secret scanning and linting must pass before merge.

## Exceptions

- Emergency mitigations may bypass some steps with an incident record and follow-up review.
