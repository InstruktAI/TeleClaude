---
description: 'InstruktAI Python logging standard. Logfmt format, dual-level control, structured pairs, tail-friendly output.'
visibility: 'public'
---

# Logging — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/python/core.md

## Rationale

Python's standard library offers several ways to emit unstructured diagnostics. Owning the shared logger, its configuration call, its level plumbing, and its third-party spam filtering here keeps the generic observability contract language-neutral and gives Python tooling and review one precise source.

## Scope

- Python services and scripts that emit logs.
- Python logger selection, configuration, log-file location, and level environment wiring.

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

Direct `print` calls and temporary `logging` probes are not production diagnostics: remove them, or convert them to the shared logger at the level the observability contract assigns.

Level assignment, observation-record admissibility, structured-field discipline, never-log rules, identifier integrity, and boundary coverage follow the generic observability contract (`software-development/policy/observability`). This policy owns only how Python realizes it.

1. Configure logging once at process start with `configure_logging(...)`.
2. Use structured key/value logging via the shared logger.
3. Set `{ENV_PREFIX}_LOG_LEVEL` and third-party log filters as needed.

## Enforcement

- Noisy logs hide important signals; tune levels and logger filters.
- Missing logs usually mean loggers are misconfigured or filtered out.

## Exceptions

- None. If a deviation is required, document the rationale and get explicit approval.

## See Also

- ~/.teleclaude/docs/software-development/policy/observability.md
