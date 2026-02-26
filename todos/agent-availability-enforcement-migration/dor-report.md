# DOR Report: agent-availability-enforcement-migration

## Gate Verdict: PASS (score 8/10)

### Gate 1: Intent & Success — PASS

The problem statement is explicit (unavailable agents still launching), the
outcome is explicit (single routable-agent policy), and success criteria are
8 concrete, testable items mapped to functional requirements.

### Gate 2: Scope & Size — PASS (cross-cutting but bounded)

This is intentionally cross-surface (API, daemon, adapters, cron, CLI) because
the regression is cross-surface. Scope is bounded to one behavioral invariant:
runtime agent routing enforcement. The plan structures work into 5 phases that
can be committed incrementally. Fits a single AI session.

### Gate 3: Verification — PASS

Verification path is concrete:

1. Targeted unit tests per migrated surface (9 test files)
2. Live CLI verification with `telec agents status` + session launch commands
3. Daemon log assertions for rejection observability
4. Demo plan is executable with concrete commands

### Gate 4: Approach Known — PASS

The technical path is proven: `helpers/agent_cli.py::_pick_agent` already
implements the full availability check (enabled + binary + DB status + degraded +
expiry). The core resolver adapts this to async context using `db.get_agent_availability`.
All call sites are enumerated in `input.md` and verified against codebase.

**Degraded policy decision — resolved:** The existing `_pick_agent` implements
Option B (block degraded for all selection — explicit and auto). This is the
established behavior. The core resolver MUST adopt the same semantics to avoid
a behavioral split between CLI and daemon surfaces. Requirements updated to
lock Option B.

### Gate 5: Research Complete — PASS (auto)

No third-party integrations or dependencies are introduced.

### Gate 6: Dependencies & Preconditions — PASS

The previously-open degraded policy decision is resolved by codebase precedent
(Option B). All other preconditions are satisfied:

- DB APIs exist and are authoritative
- Call sites are enumerated and verified
- No external system dependencies

### Gate 7: Integration Safety — PASS

The migration is incremental and merge-safe:

1. Core helper lands first (Phase 1)
2. API and daemon surfaces migrate next (Phase 2)
3. Adapters and automation migrate last (Phase 3)
4. Tests cover all phases (Phase 4)
5. Behavioral change is constrained to rejecting non-routable agents

### Gate 8: Tooling Impact — PASS (auto)

No scaffolding/tooling procedure change is required.

## Plan-to-Requirement Fidelity

All plan tasks trace to requirements. No contradictions found:

| Task    | Requirements  | Verified                           |
| ------- | ------------- | ---------------------------------- |
| 0.1     | FR2           | Policy lock — resolved to Option B |
| 1.1     | FR1, FR2      | Core resolver + degraded central   |
| 1.2     | FR1, FR4      | Mapper default removal             |
| 2.1     | FR1, FR3      | API enforcement                    |
| 2.2     | FR1, FR4, FR6 | Handler + daemon + logging         |
| 3.1     | FR5, FR6      | Adapter migration                  |
| 3.2     | FR5, FR7      | Cron + CLI scaffold                |
| 4.1/4.2 | All FR        | Verification                       |

## Codebase Verification

Call sites confirmed against codebase:

- `api_server.py:552` — `_resolve_enabled_agent` uses enabled-only, no availability check
- `api_models.py:491` — `RunCommandRequest.agent` defaults to `"claude"`
- `command_mapper.py:41` — `_default_agent_name()` uses `get_enabled_agents()` only
- `command_handlers.py:1556,1672,1795,1883` — `assert_agent_enabled` (enabled-only)
- `discord_adapter.py:135-148` — `_get_enabled_agents` + `_default_agent` (enabled-only, fallback `"claude"`)
- `telegram_adapter.py:428,497` — hardcoded `auto_command="agent claude"`
- `hooks/whatsapp_handler.py:46` — hardcoded `auto_command="agent claude"`
- `cron/runner.py:225` — `config.agent or "claude"`
- `cli/telec.py:2739` — bug scaffold `agent="claude"`
- `core/models.py:783,797` — dataclass defaults `agent: str = "claude"` (implicitly covered by caller migration)

## Notes for Builder

1. The core resolver must be async (daemon context uses async DB). The existing
   `_pick_agent` pattern is synchronous with raw sqlite3. Adapt the logic to use
   `db.get_agent_availability` for the async resolver.
2. `core/models.py` dataclass defaults (`agent: str = "claude"`) are structural
   and implicitly fixed by migrating callers. No direct edit needed unless the
   builder prefers explicit cleanup.
3. `api/streaming.py:121` (`session.active_agent or "claude"`) is a read path
   for running sessions, not a launch path. Out of scope — correct exclusion.
4. Task 0.1 (policy lock) is now pre-resolved: Option B. The builder can skip
   the decision step and codify Option B directly in the resolver and tests.

## Blockers

None. All gates pass.
