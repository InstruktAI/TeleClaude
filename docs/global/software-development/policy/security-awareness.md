---
description: Security posture, defense in depth, OWASP surface, auth, crypto, transport,
  secrets, supply chain, observability. Assume breach, fail closed, contain blast radius.
id: software-development/policy/security-awareness
scope: domain
type: policy
---

# Security Awareness — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/code-quality.md

## Rules

### Posture

Assume breach. Design every layer as if the layer above it has already been compromised.
Fail closed, not open — denied by default, permitted only by explicit grant.
Defense in depth: no single control is the only thing preventing an exploit.
Contain blast radius — scope credentials, permissions, and network access so a compromise
in one component cannot cascade.

### Boundaries & input handling

- Validate all external input at the boundary; reject before processing.
- Use allowlists over denylists — enumerate what is permitted, block everything else.
- Encode output for its context (HTML, SQL, shell, URL) — never interpolate raw values.
- Treat deserialized data as untrusted; validate structure and types after parsing.
- Reject path traversal attempts; canonicalize paths before any filesystem access.

### OWASP attack surface

Be aware of and actively guard against:

- **Injection**: SQL, command, template, LDAP, XPath — parameterize, never concatenate.
- **XSS**: Reflected, stored, DOM-based — context-aware output encoding.
- **CSRF**: State-changing operations require origin validation or anti-CSRF tokens.
- **SSRF**: Restrict outbound requests; validate and allowlist target hosts/schemes.
- **Deserialization**: Never deserialize untrusted data into executable structures.
- **Path traversal**: Canonicalize and confine all file paths to expected roots.
- **Open redirects**: Validate redirect targets against an allowlist of trusted domains.
- **Mass assignment**: Explicitly declare which fields are settable; never bind raw input to models.

### Authentication & authorization

- Tokens have explicit lifetimes; enforce expiry and support revocation.
- Session invalidation must be immediate and server-side, not client-dependent.
- Guard against replay attacks — use nonces, timestamps, or one-time tokens.
- Beware TOCTOU (time-of-check-time-of-use) — re-validate authorization at the point of action.
- Apply role-based or attribute-based access control; never trust client-supplied roles.
- Rate-limit authentication endpoints; implement account lockout or exponential backoff.

### Cryptography

- Use proven, audited libraries — never implement custom cryptographic primitives.
- Use constant-time comparison for secrets, tokens, and hashes to prevent timing attacks.
- Generate secrets and tokens with cryptographically secure random sources only.
- Key rotation must be supported by design; hardcoded keys are a vulnerability.
- Hash passwords with modern adaptive algorithms (argon2, bcrypt, scrypt) — never raw SHA/MD5.

### Transport & channel security

- TLS everywhere — no plaintext transport for sensitive data, even internally.
- Validate certificates; do not disable verification in production.
- Pin certificates or public keys where feasible for critical connections.
- Use mutual TLS or equivalent authentication for service-to-service communication.
- Protect Unix sockets and IPC channels with filesystem permissions.

### Secrets management

- Secrets never enter version control, logs, error messages, or client responses.
- Load secrets from environment variables or dedicated secret stores — never hardcode.
- Scope secret access to the component that needs it; no shared root credentials.
- Rotate secrets on a schedule and immediately on suspected compromise.
- Scrub secrets from memory when no longer needed where the language allows it.

### Least privilege & blast radius

- Grant the minimum permissions required for the task; revoke when no longer needed.
- Isolate components so a compromise in one cannot reach others (process, network, filesystem).
- Use separate credentials per service and environment; never share production keys with dev.
- Prefer short-lived credentials and tokens over long-lived ones.
- Drop elevated privileges as early as possible in the execution path.

### Supply chain

- Pin dependency versions and lock files; audit transitive dependencies.
- Verify package integrity via checksums or signatures before installation.
- Monitor for known vulnerabilities in dependencies (CVE databases, automated scanning).
- Minimize dependency surface — fewer dependencies means fewer attack vectors.
- Review and approve new dependencies before adoption.

### Observability & incident readiness

- Log security-relevant events (auth attempts, privilege changes, access denials) for audit.
- Never log secrets, tokens, full payloads with credentials, or PII.
- Include correlation IDs for tracing requests across service boundaries.
- Detect anomalies: unexpected access patterns, privilege escalation attempts, repeated failures.
- Design for forensic capability — logs must survive the compromise they record.

### Error handling as security surface

- Never expose stack traces, internal paths, or system details to external callers.
- Use generic error messages externally; log detailed diagnostics internally.
- Avoid timing oracles — error paths should take consistent time regardless of failure reason.
- Fail closed: if a security check cannot complete, deny access rather than defaulting to allow.

### Escalation triggers

Always escalate before:

- Changing authentication or authorization boundaries.
- Modifying encryption, credential handling, or key management.
- Exposing new external entry points or APIs.
- Adding or updating dependencies with native code or broad permissions.
- Disabling or weakening any existing security control.

## Rationale

- Assume-breach posture limits damage when (not if) controls fail.
- Defense in depth ensures no single vulnerability is exploitable in isolation.
- Dense coverage across attack surfaces activates systematic security reasoning.

## Scope

- Applies to all code, infrastructure, and configuration that touches user data, credentials,
  network boundaries, or external integrations.

## Enforcement

- Security-sensitive changes require explicit review and documented approval.
- Automated secret scanning, dependency auditing, and linting must pass before merge.
- OWASP-relevant patterns are flagged during code review.

## Exceptions

- Emergency mitigations may bypass steps with an incident record and follow-up review.
