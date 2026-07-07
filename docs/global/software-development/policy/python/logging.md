---
description: 'InstruktAI Python logging standard. Logfmt format, dual-level control, structured pairs, tail-friendly output.'
visibility: 'public'
---

# Logging — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/python/core.md

## Rationale

Use the shared InstruktAI logger to keep logs readable, tail-friendly, and free of third-party spam.

## Scope

- Applies to all Python services and scripts that emit logs.
- Standardization keeps logs searchable for operators and agents.

## Rules

- PyPI package: `instruktai-python-logger`
- Import module: `instrukt_ai_logging`

Call `configure_logging(...)` exactly once at process start:

```python
from instrukt_ai_logging import configure_logging

configure_logging("myapp")
```

- Single primary log file per service: `$XDG_STATE_HOME/instrukt-ai/{app}/{app}.log` (fallback `~/.local/state/instrukt-ai/{app}/{app}.log` when `XDG_STATE_HOME` is unset)
- Format: logfmt-style `key=value` pairs (easy for humans + AIs to grep)
- Prefer structured pairs over interpolated strings

```python
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)
logger.info("job_started", job_id=job_id, user_id=user_id)
```

**Our code vs third-party:**

- `{ENV_PREFIX}_LOG_LEVEL` - Our code (loggers with app prefix)
- `{ENV_PREFIX}_THIRD_PARTY_LOG_LEVEL` - Everything else

**Spotlight for third-party debugging:**

- `{ENV_PREFIX}_THIRD_PARTY_LOGGERS` - Comma-separated logger prefixes
- If set: only those third-party prefixes use configured level
- All other third-party loggers forced to WARNING+

Example:

```bash
export MYAPP_LOG_LEVEL=DEBUG
export MYAPP_THIRD_PARTY_LOG_LEVEL=WARNING

export MYAPP_THIRD_PARTY_LOG_LEVEL=INFO
export MYAPP_THIRD_PARTY_LOGGERS="httpcore,httpx,telegram"
```

The log root only follows `XDG_STATE_HOME`; there is no per-invocation override. Never point
`XDG_STATE_HOME` (or any log-path env var) at a session-scoped or scratchpad directory in a
persistent shared file (`.env`, a service plist, checked-in config) — a value like that outlives
the session that set it and silently redirects every future process, including production
daemons, into a path nothing else reads and that eventually disappears.

- **INFO** - Business-relevant events (user-visible state changes, lifecycle, deploy status)
- **DEBUG** - Successful outcomes (one line per operation with duration/summary)
- **TRACE** - High-volume chatter (start lines, loop ticks, raw payloads)
- **WARNING** - Recoverable anomalies (retries, unexpected states, missing optional data)
- **ERROR/CRITICAL** - Failures or contract violations that should be fixed

**Start/End Pairs:**

- Prefer **one line** per operation: log completion at DEBUG with duration
- If keeping start line, log it at TRACE and completion at DEBUG

**Consistency:**

- Reuse same message template for same event
- Favor structured key/value pairs (`event=heartbeat_sent`, `duration_ms=...`)
- Throttle or aggregate repetitive logs

**Never Log:**

- Passwords, tokens, API keys, PII
- Entire payloads in production (use TRACE if needed)
- Success/failure of every minor operation (aggregate instead)

**Identifier integrity:**

- Never truncate UUIDs or identifiers in log fields or format strings. Use the full value.
- Correct: `logger.info("session started", session_id=session_id)`
- Wrong: `logger.info("session started", session_id=session_id[:8])`
- Applies to all ID variables: `session_id`, `native_session_id`, `operation_id`, `voice_id`,
  `message_id`, and any future identifier.

1. Configure logging once at process start with `configure_logging(...)`.
2. Use structured key/value logging via the shared logger.
3. Set `{ENV_PREFIX}_LOG_LEVEL` and third-party log filters as needed.
4. Avoid logging secrets or full payloads.

## Enforcement

- Noisy logs hide important signals; tune levels and logger filters.
- Missing logs usually mean loggers are misconfigured or filtered out.

## Exceptions

- None. If a deviation is required, document the rationale and get explicit approval.
