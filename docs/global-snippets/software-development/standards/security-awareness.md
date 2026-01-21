---
description:
  Secrets management, input validation, OWASP awareness, secure defaults.
  Never commit secrets, validate boundaries.
id: software-development/standards/security-awareness
requires:
  - software-development/standards/code-quality
scope: domain
type: policy
---

# Security Awareness

## Requirements

@docs/global-snippets/software-development/standards/code-quality.md

## Principle

Security is not optional. Treat every input as untrusted, validate at boundaries, fail safely, and never expose secrets.

## Secrets Management

1. **Never commit secrets**
   - No API keys, passwords, tokens, credentials in version control
   - Use environment variables or secure vaults
   - Provide `.env.example` templates, never `.env` files

2. **Never log sensitive data**
   - No passwords, tokens, PII, API keys in logs
   - Redact sensitive fields before logging
   - Be mindful of structured logging that captures all fields

3. **Rotate and revoke**
   - Treat any leaked secret as compromised
   - Rotate immediately if exposure suspected
   - Use short-lived tokens where possible

## Input Validation

1. **Validate at boundaries**
   - Check all external input (user input, API calls, file uploads)
   - Whitelist valid patterns, don't blacklist dangerous ones
   - Reject invalid input early with clear errors

2. **Never trust client input**
   - Always validate server-side, even if client validates
   - Don't rely on hidden fields or disabled buttons for security
   - Treat all HTTP request data as potentially malicious

## Common Vulnerabilities (OWASP Awareness)

1. **Command Injection**
   - Never construct shell commands from user input
   - Use parameterized APIs instead of string concatenation
   - If unavoidable, use strict allowlists and escaping

2. **SQL Injection**
   - Always use parameterized queries or ORMs
   - Never concatenate user input into SQL strings
   - Escape special characters if dynamic SQL required

3. **Cross-Site Scripting (XSS)**
   - Escape all user-generated content in HTML
   - Use framework auto-escaping (React, Vue, Angular)
   - Set Content-Security-Policy headers

4. **Path Traversal**
   - Validate file paths against allowed directories
   - Reject `..` sequences and absolute paths
   - Use safe path join functions

5. **Authentication & Authorization**
   - Require authentication for sensitive operations
   - Check authorization on every request (don't assume)
   - Use secure session management

## Secure Defaults

1. **Fail closed, not open**
   - Default to denying access
   - Explicit opt-in for permissions
   - Log authorization failures

2. **Minimal exposure**
   - Don't expose stack traces to users
   - Limit error detail in production
   - Use generic error messages for auth failures

3. **Defense in depth**
   - Multiple layers of security
   - Don't rely on single control
   - Validate at every boundary

## Code Review Security Checklist

Before approving code, verify:

- [ ] No secrets committed
- [ ] No sensitive data in logs
- [ ] Input validation at boundaries
- [ ] No command/SQL injection vectors
- [ ] XSS prevention (escaped output)
- [ ] Path traversal protection
- [ ] Authorization checks present
- [ ] Secure defaults used
- [ ] Error messages don't leak info

## When to Escalate

Per baseline autonomy policy, **always escalate** before:

- Changing authentication or authorization
- Modifying encryption or secrets handling
- Exposing new network endpoints
- Changing access control boundaries
- Adding credential management
