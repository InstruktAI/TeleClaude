---
description:
  InstruktAI Python logging standard. Logfmt format, dual-level control,
  structured pairs, tail-friendly output.
id: software-development/guides/python/logging
scope: domain
type: guide
---

# Logging — Guide

## Goal

- @docs/software-development/guides/python/core
- @docs/software-development/policy/code-quality

@~/.teleclaude/docs/software-development/guides/python/core.md
@~/.teleclaude/docs/software-development/standards/code-quality.md

Use the shared InstruktAI logger to keep logs readable, tail-friendly, and free of third-party spam.

- PyPI package: `instruktai-python-logger`
- Import module: `instrukt_ai_logging`

Call `configure_logging(...)` exactly once at process start:

```python
from instrukt_ai_logging import configure_logging

configure_logging("myapp")
```

- Single primary log file per service: `/var/log/instrukt-ai/{app}/{app}.log`
- Format: logfmt-style `key=value` pairs (easy for humans + AIs to grep)
- Prefer structured pairs over interpolated strings

```python
import logging

logger = logging.getLogger("instrukt_ai.myapp.worker")
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

```bash
export INSTRUKT_AI_LOG_ROOT="$PWD/logs"
```

Changes target path to: `$INSTRUKT_AI_LOG_ROOT/{app}/{app}.log`

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

- TBD.

- TBD.

- TBD.

## Steps

- TBD.

## Outputs

- TBD.

## Recovery

- TBD.
