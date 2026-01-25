---
description:
  Secrets management, input validation, OWASP awareness, secure defaults.
  Never commit secrets, validate boundaries.
id: software-development/policy/security-awareness
scope: domain
type: policy
---

# Security Awareness — Policy

## Rule

- @docs/software-development/policy/code-quality

@~/.teleclaude/docs/software-development/standards/code-quality.md

Security is a baseline constraint. Treat inputs as untrusted, validate at boundaries, and protect secrets by default.

- Secrets never enter version control or logs.
- Validation happens at the boundary, not deep in the core.
- Defaults are safe; permissions are explicit.

Always escalate before:

- Changing authentication or authorization boundaries.
- Modifying encryption or credential handling.
- Exposing new external entry points.

- TBD.

- TBD.

- TBD.

- TBD.

## Rationale

- TBD.

## Scope

- TBD.

## Enforcement

- TBD.

## Exceptions

- TBD.
