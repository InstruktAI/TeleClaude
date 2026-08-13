---
description: Role-aware, availability- and quota-sensitive fresh-session routing with compact quota-pressure visibility.
delivered_by:
  - agent-usage-aware-dispatch
---

# Usage Aware Agent Dispatch — Spec

## Required reads

@docs/project/spec/domain/agent_runtime.md
@docs/project/spec/feature/agent_runtime/session-lifecycle.md
@docs/project/spec/feature/agent_runtime/run-session-with-command.md

## What it is

Usage-aware agent dispatch adds normalized quota state to fresh-session routing.
Quota pressure is a preference signal, not hard unavailability. Automatic
dispatch may shift work away from a pressured preferred agent, while manual
fresh-session dispatch honors the human-selected agent whenever that agent is
enabled and not hard unavailable.

The feature also exposes compact quota-pressure fragments in agent availability
surfaces. Quiet availability remains quiet below pressure thresholds. Once a
threshold is crossed, the visible marker becomes a compact remaining-percentage
fragment such as `5H:8%` or `W:17%`.

The usage collector also defines no-session provider probes. A provider probe or
one-shot helper used for quota collection must not create a native agent session
log, native session-list entry, brain transcript, or TeleClaude headless session
row. The safe provider invocation shape is part of the contract and is owned by
shared helper code; callers do not opt into it with an extra flag.

## Canonical fields

### Dispatch modes

**Automatic preference**
: Fresh work where the caller has not made a human agent choice. This includes
lifecycle workers, generated spawn instructions, scheduled jobs without a
fixed-agent contract, adapter-created default sessions, and omitted-agent API
requests. Quota pressure may reroute automatic preference to a better-headroom
enabled available agent.

**Manual preference**
: Fresh work where a human explicitly selects or supplies an agent, for example
through the TUI New Session modal or a terminal `--agent` argument. Quota pressure
and degraded state do not reroute manual preference. Hard unavailable state still
applies; when the selected agent is unavailable, dispatch selects the next best
enabled available agent and reports the fallback reason.

**Fixed agent**
: Work bound to an existing native runtime or a declared fixed-agent job
contract. Fixed-agent work never cross-agent substitutes. It either continues
with the bound agent or fails with an agent-specific reason.

### Automatic role preferences

Every automatic fresh-session dispatch whose command maps through the canonical
command-role registry starts from one exhaustive, ordered job-role matrix. The
order is policy: availability, degradation, producer separation, and quota
pressure may move selection down a row, but incidental configuration iteration
order never decides the fallback.

| Job role                | Context | Ordered agents        |
| ----------------------- | ------- | --------------------- |
| `prepare-orchestrator`  | feature | Claude, Codex, Gemini |
| `prepare-orchestrator`  | change  | Codex, Claude, Gemini |
| `prepare-orchestrator`  | bug     | Codex, Claude, Gemini |
| `work-orchestrator`     | all     | Codex, Claude, Gemini |
| `builder`               | all     | Codex, Claude, Gemini |
| `reviewer`              | all     | Codex, Claude, Gemini |
| `finalizer`             | all     | Codex, Claude, Gemini |
| `intaker`               | all     | Claude, Codex, Gemini |
| `planner`               | all     | Claude, Codex, Gemini |
| `diagnoser`             | all     | Codex, Claude, Gemini |
| `architect`             | all     | Claude, Codex, Gemini |
| `architecture-reviewer` | all     | Claude, Codex, Gemini |
| `task-preparer`         | all     | Claude, Codex, Gemini |
| `task-runner`           | all     | Codex, Claude, Gemini |
| `drift-analyzer`        | all     | Codex, Claude, Gemini |
| `po-emulator`           | all     | Claude, Gemini, Codex |
| `create-orchestrator`   | all     | Gemini, Claude, Codex |
| `artist`                | all     | Gemini, Claude, Codex |
| `frontender`            | all     | Gemini, Claude, Codex |
| `integrator`            | all     | Codex, Claude, Gemini |

The global automatic fallback order is Codex, Claude, Gemini. It applies only
when a fresh-session command has no mapped job role or the caller supplies no
role-specific context. A missing matrix row for a known job role is a contract
defect: dispatch uses the global order to remain operable and emits a warning.
The matrix is exhaustive over the job-role enum, and its implementation checks
that exhaustiveness mechanically.

For reviewer roles, an eligible agent different from the producer is promoted
ahead of the producer while preserving the row's relative order. When only the
producer's agent is eligible, it still performs the review.

### Candidate resolution and observability

Automatic selection resolves one row in this order:

1. Remove agents that are not configured, disabled, or hard unavailable.
2. Apply reviewer producer separation.
3. Prefer non-degraded candidates over degraded candidates.
4. Apply quota-pressure and normalized-headroom routing within the eligible
   health band.
5. Use matrix order as the stable tie-breaker.

When the selected agent differs from the row's first candidate, dispatch emits
one structured warning carrying the job role, todo kind when applicable,
preferred agent, selected agent, and exact fallback reason. Reasons include
`preferred_disabled`, `preferred_unavailable`, `preferred_degraded`,
`quota_pressure`, and `producer_separation`. An unmapped command or missing
matrix row emits `job_unmapped` or `matrix_missing` respectively and uses the
Codex-first global order. No eligible candidate is a hard dispatch failure.

### Provider usage probes

**Claude usage probe**
: The tested print-mode invocation of `/usage`:
`claude -p '/usage' --output-format json --no-session-persistence --no-chrome --strict-mcp-config --tools '' --setting-sources user --settings '{"forceLoginMethod":"claudeai","enabledMcpjsonServers":[],"disableAllHooks":true}'`.
The collector parses the JSON envelope's `result` text. `--bare` is not used
because it returns print-session accounting instead of subscription quota.
`/usage --json` is not used because it is not the proven zero-turn subscription
usage payload.

**Codex usage probe**
: A passive read of the newest existing `token_count` event under
`~/.codex/sessions/YYYY/MM/DD/*.jsonl`, using
`payload.rate_limits.primary` and `payload.rate_limits.secondary`. The collector
does not invoke `codex exec`, Codex `/status`, or a TUI fallback to obtain quota
because that would risk a model turn or a native session artifact.

**Antigravity usage probe**
: A short-lived local language-server RPC call to
`RetrieveUserQuotaSummary`, using a temporary log/process wrapper that is torn
down after the response. `agy -p`, `agy --prompt`, and `agy --print` are not used
for `/usage` because they treat the text as model input and can consume a turn.

### Use cases

#### UC-UAAD-1: Automatic dispatch keeps the preferred agent below pressure

```
Given automatic fresh dispatch has a preferred agent
And the preferred agent is enabled, available, and below quota-pressure thresholds
When the dispatch decision is resolved
Then the preferred agent is selected
And no fallback reason is emitted
```

#### UC-UAAD-2: Automatic dispatch reroutes from quota pressure

```
Given automatic fresh dispatch has a preferred agent
And the preferred agent is under quota pressure
And another enabled available agent has better normalized headroom
When the dispatch decision is resolved
Then the better-headroom agent is selected
And the fallback reason names quota pressure on the preferred agent
```

#### UC-UAAD-3: Automatic dispatch still saturates when all candidates are pressured

```
Given every enabled available candidate is under quota pressure
When the dispatch decision is resolved
Then dispatch selects the enabled available candidate with the best normalized headroom
And pressure alone does not block fresh work
```

#### UC-UAAD-4: Manual preference ignores quota pressure

```
Given a human manually selects an enabled agent for a fresh session
And that agent is available but under quota pressure
When the dispatch decision is resolved in manual-preference mode
Then the selected agent is dispatched
And quota pressure does not reroute the session to a different agent
```

#### UC-UAAD-5: Manual preference may choose a degraded agent

```
Given a human manually selects an enabled degraded agent for a fresh session
And that agent is not hard unavailable
When the dispatch decision is resolved in manual-preference mode
Then the selected agent is dispatched
And degraded status is surfaced as context rather than treated as a reroute trigger
```

#### UC-UAAD-6: Manual preference falls back on hard unavailable state

```
Given a human manually selects an enabled agent for a fresh session
And that selected agent is hard unavailable because of operator status or provider exhaustion
And another enabled available agent exists
When the dispatch decision is resolved in manual-preference mode
Then the next best enabled available agent is selected
And the fallback reason names the selected agent's unavailable reason
```

#### UC-UAAD-7: Fixed-agent work never cross-agent substitutes

```
Given work is bound to an existing native session or a declared fixed-agent job
When the bound agent is unavailable
Then the dispatch decision does not select a different agent
And the caller receives an agent-specific refusal or continuation status
```

#### UC-UAAD-8: Compact pressure visibility reaches all availability clients

```
Given the usage snapshot crosses the five-hour or weekly pressure threshold
When agent availability is returned through HTTP, WebSocket, TUI bootstrap, or frontend API proxy
Then the availability payload carries compact pressure fragments
And footer renderers can display those fragments without parsing provider-specific state
```

#### UC-UAAD-9: Provider probes do not create native sessions

```
Given the usage collector probes Claude, Codex, and Antigravity
When each provider's quota state is collected
Then no probe creates a native agent session log
And no probe creates a native session-list entry
And no probe creates a brain transcript
And no probe creates a TeleClaude headless session row
And Claude uses the tested print-mode `/usage` invocation
And Codex reads existing `token_count.payload.rate_limits` metadata
And Antigravity uses the local `RetrieveUserQuotaSummary` RPC path
```

#### UC-UAAD-10: Automatic dispatch uses the complete ordered role matrix

```
Given a fresh automatic dispatch whose slash command maps to a known job role
When the dispatch decision is resolved
Then its initial candidate order comes from the single role-preference matrix
And every canonical job role has a matrix entry
And configuration iteration order does not determine fallback order
```

#### UC-UAAD-11: Prepare selection includes todo kind

```
Given the lifecycle runner automatically dispatches a prepare orchestrator
When the todo kind is feature
Then the ordered candidates are Claude, Codex, Gemini
When the todo kind is change or bug
Then the ordered candidates are Codex, Claude, Gemini
```

#### UC-UAAD-12: Work and worker dispatch use the same resolver

```
Given the lifecycle runner dispatches a work orchestrator
Or an orchestrator dispatches a builder, reviewer, finalizer, diagnosis peer,
drift analyzer, artist, or frontender
Or the integration bridge dispatches an integrator
When the fresh session is created without a human-selected agent
Then the command's job role is resolved through the same role matrix and
dispatch-decision helper
And generated orchestration scripts do not ask the orchestrator to select an
agent independently
```

#### UC-UAAD-13: Reviewer selection prefers independent evaluation

```
Given an automatic reviewer dispatch whose producer used the row's first agent
And a different non-degraded enabled available agent exists
When the reviewer candidate order is resolved
Then the different agent is promoted ahead of the producer
And the row's relative order is otherwise preserved
And if no different agent is eligible the producer agent may review
```

#### UC-UAAD-14: Automatic fallback is explicit and observable

```
Given automatic selection does not choose the first candidate in its role row
When dispatch proceeds with another eligible agent
Then one structured warning records the job role, todo kind when applicable,
preferred agent, selected agent, and exact fallback reason
And an unmapped command or missing known-role row uses Codex, Claude, Gemini
And records job_unmapped or matrix_missing respectively
And no eligible candidate causes a hard dispatch failure
```

## Known caveats

- Manual preference is not the same as fixed-agent continuation. A human choice
  is strong preference for a new session; it still respects hard unavailable
  state and can fall back with a visible reason.
- Quota pressure is deliberately asymmetric: automatic dispatch may avoid it,
  manual preference may choose through it, and fixed-agent work does not consult
  it for substitution.
- Unknown, stale, or failed quota data is diagnostic state. It never proves that
  an agent is healthy, but it also does not by itself block dispatch.
- The prepare orchestrator normally performs intake, architecture drafting, and
  planning inline. Those phase roles inherit the already-selected prepare
  session during normal preparation; their own matrix rows govern only fresh
  direct invocation.
- One-shot safety is not caller-selectable. If a provider path cannot satisfy the
  no-session contract, the helper refuses that path instead of falling back to an
  invocation that creates native session artifacts.
- Automated tests do not assert third-party CLI filesystem side effects. The
  TeleClaude contract binds which helper and provider invocation shapes are used.
