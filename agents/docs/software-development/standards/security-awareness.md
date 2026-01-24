---
description:
  Secrets management, input validation, OWASP awareness, secure defaults.
  Never commit secrets, validate boundaries.
id: software-development/standards/security-awareness
scope: domain
type: policy
---

# Security Awareness

## Required reads

- @software-development/standards/code-quality

## Requirements

@~/.teleclaude/docs/software-development/standards/code-quality.md

## Principle

Security is a baseline constraint. Treat inputs as untrusted, validate at boundaries, and protect secrets by default.

## Rules

- Secrets never enter version control or logs.
- Validation happens at the boundary, not deep in the core.
- Defaults are safe; permissions are explicit.

## When to Escalate

Always escalate before:

- Changing authentication or authorization boundaries.
- Modifying encryption or credential handling.
- Exposing new external entry points.
