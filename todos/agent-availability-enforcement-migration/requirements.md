# Requirements: agent-availability-enforcement-migration

## Goal

Enforce one canonical routable-agent policy across all session creation,
agent launch, and agent restart paths so agents marked unavailable are never
selected or started by bypass paths.

## Why

Regression evidence from 2026-02-26 shows `claude` was marked unavailable
(`unavailable_until=2026-02-26T19:00:00Z`) but still launched through both:

1. explicit selection (`telec sessions run --agent claude`)
2. implicit default selection (`telec sessions run` without `--agent`)

Current behavior is inconsistent because most runtime paths only check
`enabled` state and do not enforce DB-backed availability status.

## Scope

### In scope

1. Define one core resolver for routable agent selection and validation.
2. Apply resolver to all runtime launch/restart entry points listed in `input.md`.
3. Remove hardcoded/default runtime agent choices that bypass availability policy.
4. Add deterministic logging for availability rejections with call-site source.
5. Add regression tests covering API, daemon, mapper/handlers, adapters, cron, and CLI scaffolding surfaces.

### Out of scope

1. New agent availability statuses or schema changes.
2. TUI rendering/pill behavior changes.
3. Policy redesign for non-runtime advisory guidance text.

## Functional Requirements

### FR1: Canonical Routable-Agent Resolver

1. A single core helper MUST validate agent routing using:
   - known agent check
   - config enabled check
   - DB availability/degraded status check
2. The helper MUST support:
   - explicit requested agent validation
   - default/auto agent selection when no explicit agent is provided
3. The helper MUST return normalized agent names and deterministic error messages.

### FR2: Degraded Policy Is Single-Sourced

1. Degraded behavior MUST be decided once and implemented centrally.
2. All call sites MUST consume the same degraded policy semantics.
3. No call site may bypass degraded-policy enforcement with custom fallback logic.

### FR3: API Runtime Enforcement

1. `/sessions` and `/sessions/run` MUST use the canonical resolver for both:
   - explicit `agent` requests
   - implicit/default selection
2. Validation of `auto_command` agent targets in `/sessions` MUST use the canonical resolver.
3. API request model defaults MUST not hardcode a specific runtime agent that bypasses resolver selection.

### FR4: Command Execution Enforcement

1. `start_agent`, `resume_agent`, `agent_restart`, and `run_agent_command`
   MUST enforce routable-agent policy (not enabled-only policy).
2. Daemon auto-command execution for `agent` and `agent_then_message`
   MUST enforce routable-agent policy before process launch.

### FR5: Adapter and Automation Surfaces

1. Session launch paths in Discord, Telegram, Telegram callback handlers,
   WhatsApp hook handling, cron runner, and bug scaffolding MUST not embed
   availability-bypassing runtime defaults.
2. Where explicit agent choices are offered, unavailable targets MUST be rejected
   through the canonical policy path.

### FR6: Observability

1. Availability rejection logs MUST include:
   - source path/category (api, daemon, handler, adapter, cron, cli scaffold)
   - requested agent (if any)
   - rejection reason/status (`disabled`, `unavailable`, `degraded`, `unknown`)
2. Logs MUST be queryable with `instrukt-ai-logs teleclaude --grep`.

### FR7: Backward-Safe Integration

1. Migration MUST be incremental and mergeable without daemon lifecycle changes.
2. Existing command contracts remain compatible except for correct rejection
   of non-routable agents.

## Success Criteria

- [ ] One canonical routable-agent resolver exists and is used by all listed launch/restart paths
- [ ] No runtime hardcoded/default agent path bypasses availability policy
- [ ] `/sessions` and `/sessions/run` block unavailable agent launches (explicit and implicit)
- [ ] Daemon `agent` and `agent_then_message` paths block unavailable launches
- [ ] Command handlers and mapper defaults no longer allow enabled-only bypass behavior
- [ ] Adapter and automation launch paths respect canonical routable-agent policy
- [ ] Structured/consistent rejection logs are emitted and discoverable
- [ ] Regression tests cover all migrated surfaces and pass

## Constraints

1. Keep single-database behavior (`teleclaude.db`) and reuse existing DB methods.
2. Preserve adapter/core boundaries while introducing the shared resolver.
3. Do not introduce host-level service changes or new lifecycle commands.
4. No new third-party dependencies are required.

## Dependencies & Preconditions

1. **Degraded semantics — Option B (block all selection):**
   The existing proven resolver (`helpers/agent_cli.py::_pick_agent`) already blocks
   degraded agents for both explicit and auto-selection paths. The canonical core
   resolver MUST adopt the same behavior. Options A and C are rejected because they
   would create a behavioral split between CLI and daemon surfaces.
2. Existing availability table and DB APIs (`get_agent_availability`, expiry clearing) remain authoritative.

## Risks

1. Cross-surface migration risk: missing one call site can preserve the regression.
2. Behavior-change risk: stricter enforcement can break workflows that depended on fallback defaults.
3. Async/sync seam risk in mapper/default paths if selection is done before DB access is available.

## Research

No third-party integration or library changes are introduced.
`Research complete` gate is auto-satisfied.
