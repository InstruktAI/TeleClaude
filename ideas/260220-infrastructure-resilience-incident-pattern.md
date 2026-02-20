# Infrastructure Resilience: Incident Pattern Analysis

**Incidents observed:** Five related memory entries (IDs 25, 30, 31, 40, 41, 42) document recurring infrastructure visibility and reliability problems:

1. **Port exhaustion (ID 41)** - MozMini runner offline for 6 days, silently failed (Feb 10-16). Service appeared running in launchd despite network failure. Root cause: ephemeral port exhaustion, workaround: sysctl config change.

2. **Session observability failure (ID 31)** - Codex sessions unobservable until first turn completes. Orchestrator wrongly interprets missing session file as ended session, causing cascading state issues.

3. **Session lifecycle ambiguity (ID 30)** - `get_session_data` returning "session not found" doesn't mean session is ended. Operators must call `end_session` explicitly per procedure, but procedure is not universally followed.

4. **MCP coupling fragility (ID 40)** - `get_context` depends on MCP, which depends on daemon. When daemon is down, we lose our knowledge entrypoint. Single point of failure.

5. **Daemon restart friction (ID 25)** - Agents fail to restart daemon after code changes, then claim validation passed against stale state. Documented but recurring.

6. **HTTPS blocking (ID 42)** - Little Snitch on mozmini blocks HTTPS git/Python but allows SSH. Workaround exists but adds operational friction.

**Root cause pattern:** Infrastructure lacks observability and resilience boundaries. Failures are silent, assumptions about state are not validated, and critical tools (get_context) have hard dependencies on the daemon.

**Actionable next step:** Create `docs/infrastructure-resilience/incident-summary.md` that:

- Documents each incident with timeline, root cause, and mitigation
- Identifies the observability gaps that let each fail silently
- Proposes a resilience improvement roadmap (decoupling, monitoring, state validation)
