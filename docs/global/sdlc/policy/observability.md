---
description: 'Language-neutral observability contract: log levels, boundary coverage, structured fields, never-log rules, and identifier integrity.'
visibility: 'public'
---

# Observability — Policy

## Rules

### Log levels

- **INFO** — Business-relevant events (user-visible state changes, lifecycle, deploy status)
- **DEBUG** — Successful outcomes (one line per operation with duration/summary)
- **TRACE** — High-volume chatter (start lines, loop ticks, raw payloads)
- **WARNING** — Recoverable anomalies (retries, unexpected states, missing optional data)
- **ERROR/CRITICAL** — Failures or contract violations that should be fixed

INFO is the production level: what a deployed runtime emits with no configuration change.

### Structured fields

- Context is passed as structured key/value pairs, never preformatted into the message string.
- One event token per event, reused consistently (`event=heartbeat_sent`, `duration_ms=...`).
- Repetitive records are throttled or aggregated.

### One record per operation

- Prefer a single completion record per operation, at DEBUG, carrying its duration.
- When a start line is genuinely needed, it is TRACE and the completion stays DEBUG.

### Boundary coverage

- Significant operations — external calls, state transitions, durable writes — are observable at entry or at completion, never both.

### Never log

- Passwords, tokens, API keys, PII.
- Entire payloads in production; use TRACE when a payload is genuinely needed.
- Success or failure of every minor operation; aggregate instead.

### Identifier integrity

- Identifiers are never truncated in log fields or format strings — full values only.
- This applies to every identifier the system carries: session, native session, operation, message, voice, and any future one.

## Rationale

Level semantics, boundary coverage, the never-log list, and identifier integrity are outcomes that hold whatever language implements them. Stating them once, above every language policy, gives review and tooling a single authoritative source and leaves each language policy owning only what its syntax, logger, and configuration actually decide.

When a language policy absorbs these rules instead, two failures follow together: the rules are primed as that one language's convention, and every other language is left deferring to a contract that does not exist.

## Scope

- All production code in every language, plus every project-scoped extension of this contract.
- Language logging policies own how their language realizes it: logger selection, configuration call, field syntax, level plumbing, and enforcement commands.

## Enforcement

- Reviewers cite this policy for level assignment, boundary coverage, structured-field discipline, never-log, and identifier integrity; they cite the applicable language logging policy for the mechanism.
- A language or project snippet that restates these rules instead of referencing them is wrong-owner placement under `sdlc/policy/language-policy-ownership`.

## Exceptions

- None. A deviation is a documented, approved project-scoped extension, never a silent local convention.

## See Also

- ~/.teleclaude/docs/sdlc/policy/language-policy-ownership.md
