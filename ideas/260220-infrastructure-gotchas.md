# Infrastructure Gotchas Pattern — Idea

## Summary

Three recent gotchas (Feb 14-16) reveal recurring infrastructure failures that silently break systems:

- **Little Snitch** blocks HTTPS git, forcing SSH workaround
- **Port exhaustion** silently killed MozMini runner with no error
- **Codex sessions** unobservable until first turn completes

## Pattern

All three failures share common traits:

- **Silent failures**: No immediate error signal to alert operators
- **External dependency**: Network firewalls, OS resource limits, third-party CLIs
- **Detection friction**: Required manual investigation to discover root cause
- **Workaround-first mentality**: Document the workaround, not the prevention

## Actionable Insights

1. **Need observability layer**: Add health checks for port availability, SSH connectivity, and session readiness before critical paths depend on them.

2. **Infrastructure-as-code for gotchas**: Document known gotchas in a runbook and create automated guards (e.g., pre-flight checks in daemon startup).

3. **Session lifecycle clarity**: Codex session observability gap suggests we need a session state spec that makes it clear when sessions are truly ready.

## Next Steps

Consider creating:

- `docs/project/spec/infrastructure-health-checks.md` — Pre-flight validation suite
- `teleclaude/daemon/preflight.py` — Boot-time system checks
- `docs/project/procedure/troubleshooting-gotchas.md` — Runbook for known failures

## Related Memories

- ID 42: Little Snitch blocks HTTPS git
- ID 41: Port exhaustion silently killed MozMini runner
- ID 31: Codex sessions unobservable until first turn completes
