---
id: 'general/policy/agent-dispatch'
type: 'policy'
scope: 'global'
description: 'Role-to-agent dispatch assignments. Designates which agent holds each operational role.'
---

# Agent Dispatch — Policy

## Rules

### Role assignments

| Role         | Designated agent | Excluded agents |
| ------------ | ---------------- | --------------- |
| Orchestrator | Codex            | Claude, Gemini  |
| Architect    | Claude           | —               |
| Builder      | Claude, Codex    | —               |
| Reviewer     | Claude, Codex    | —               |
| Frontend     | Gemini           | —               |

### Orchestrator

- Codex is the sole designated orchestrator.
- Claude must not take the orchestrator role — not for `next-work`, not for `prime-orchestrator`, not for any supervisory dispatch loop.
- When dispatching an orchestrator session: `telec sessions run --command /next-work --agent codex`.

### Builder and Reviewer

- Both Claude and Codex are eligible for build and review roles.
- Selection follows cognitive fit from `general/spec/agent-characteristics`: prefer Codex for exhaustive coverage and contract integrity; prefer Claude for architecture-heavy or policy-sensitive work.

### Frontend

- Gemini is the designated frontend and creative agent.

## Rationale

Codex's cognitive profile — methodical, skeptical, surfaces what others miss — is the strongest fit for the orchestrator role. The orchestrator must scrutinize worker output and maintain process integrity without drifting into implementation. Codex's resistance to over-trusting and its thoroughness make it the right fit. Claude's architectural strength is better spent in builder and reviewer roles where system-level reasoning produces output directly.

## Scope

- Applies to all agent dispatch decisions across all projects.
- Applies to orchestrated `telec todo work` and `telec todo prepare` invocations.

## Enforcement

- Orchestrator sessions must specify `--agent codex` explicitly.
- If Codex is unavailable, escalate to the human rather than falling back to Claude as orchestrator.

## Exceptions

- None.

## See Also

- general/spec/agent-characteristics
- general/concept/orchestrator
