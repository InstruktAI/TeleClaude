---
description: Provider-neutral quota collection, pressure-aware ranking, exhaustion projection, and compact quota visibility layered onto deterministic fresh-session routing.
delivered_by:
  - adaptive-usage-routing
---

# Usage-Aware Agent Dispatch — Spec

## Required reads

@docs/project/spec/feature/agent_runtime/role-aware-agent-dispatch.md

## What it is

Usage-aware dispatch extends the deterministic fresh-session candidate set with
provider-neutral quota intelligence. It never establishes eligibility: configured
inventory, enabled state, and operator availability are resolved first by the
role-aware dispatch contract. Quota state then refines automatic preference among
the candidates that remain.

Pressure is a ranking signal, not a refusal. Automatic work may move toward an
eligible agent with greater normalized headroom, while an available agent selected
manually remains selected through quota pressure. Fixed continuation never consults
quota for cross-agent substitution.

The same normalized state produces compact pressure fragments for operator
availability surfaces. Provider probing creates no agent session or model turn and
persists no raw output, credentials, access tokens, or account identity.

## Canonical fields

### Quota-pressure thresholds

Five-hour quota is under pressure at 90% consumed or more, equivalent to 10%
remaining or less. Weekly quota is under pressure at 80% consumed or more,
equivalent to 20% remaining or less. Visible fragments report remaining percentage;
routing compares normalized headroom.

### Adaptive candidate ranking

Adaptive ranking runs only after deterministic routing removes every candidate that
is unconfigured, disabled, degraded, or unavailable. An eligible candidate below
pressure stays ahead of a pressured candidate. Among candidates in the same pressure
condition, greater normalized headroom ranks first and deterministic role order is
the stable tie-breaker.

Pressure never blocks saturation. When every eligible candidate is pressured,
dispatch selects the candidate with greatest normalized headroom. Missing, stale,
or failed quota state is diagnostic uncertainty: it does not invent headroom, does
not establish health, and preserves deterministic role order where comparison is
unsupported.

### Exhaustion and operator ownership

Confirmed provider exhaustion may establish quota-owned hard unavailability through
the existing bounded availability behavior. It never overwrites an operator-owned
status or reason. Final eligibility remains governed by role-aware dispatch.

### Provider usage probes

Provider-specific collection stays behind one normalized snapshot. A probe or
one-shot helper used for quota collection creates no native agent session, session
list entry, transcript, model turn, or TeleClaude headless session row.

**Claude usage probe**
: Uses the proven no-session print-mode subscription-usage surface and parses only
its result envelope.

**Codex usage probe**
: Passively reads the newest existing rate-limit metadata and does not invoke a
Codex model session.

**Antigravity usage probe**
: Uses the local quota-summary service through a short-lived process wrapper that
is torn down after the response and never submits `/usage` as model input.

### Quota presentation and privacy

Five-hour and weekly remaining fragments appear only after their pressure threshold
is crossed; below pressure, availability presentation stays quiet. Human-facing CLI
callers may receive the exact quota-pressure reason for an adaptive fallback.
Normalized diagnostics and routing explanation are not inserted into spawned-agent
context or returned to automated runners.

### Use cases

#### UC-UAAD-1: Automatic dispatch keeps an eligible preference below pressure

```gherkin
Given an agent caller creates automatic fresh work
And the deterministic preferred agent is eligible and below quota pressure
When adaptive ranking evaluates the candidate set
Then the deterministic preferred agent remains selected
And no quota fallback reason is emitted
```

#### UC-UAAD-2: Automatic dispatch reroutes from quota pressure

```gherkin
Given an agent caller creates automatic fresh work
And the deterministic preferred agent is under quota pressure
And another eligible agent has greater normalized headroom
When adaptive ranking evaluates the candidate set
Then the greater-headroom agent is selected
And the human-facing fallback reason names quota pressure
```

#### UC-UAAD-3: Automatic dispatch saturates when all candidates are pressured

```gherkin
Given every deterministically eligible candidate is under quota pressure
When adaptive ranking evaluates the candidate set
Then the candidate with greatest normalized headroom is selected
And pressure alone does not block fresh work
```

#### UC-UAAD-4: Manual preference ignores quota pressure

```gherkin
Given a human selects an available agent for a fresh session
And that agent is under quota pressure
When adaptive routing evaluates the request
Then the human-selected agent remains selected
And quota pressure does not reroute the manual preference
```

#### UC-UAAD-6 (r2): Confirmed exhaustion respects operator ownership

```gherkin
Given a provider confirms that an agent is exhausted
When quota-owned unavailability is projected
Then the exhausted agent becomes ineligible through the deterministic availability boundary
And an existing operator-owned status or reason is not overwritten
And fixed continuation does not substitute another agent
```

#### UC-UAAD-8: Compact pressure visibility reaches operator clients

```gherkin
Given normalized quota state crosses the five-hour or weekly pressure threshold
When a human operator reads agent availability through HTTP, WebSocket, TUI bootstrap, or the frontend API proxy
Then every named surface receives compact provider-neutral remaining fragments
And five-hour pressure begins at 90% consumed or 10% remaining
And weekly pressure begins at 80% consumed or 20% remaining
And presentation stays quiet below both thresholds
```

#### UC-UAAD-9: Provider probes create no agent activity

```gherkin
Given the quota collector probes each supported provider
When collection completes or fails
Then no probe creates an agent session, model turn, transcript, or TeleClaude headless session row
And persisted state contains normalized facts and diagnostics only
And raw provider output, credentials, access tokens, and account identity are absent
```

#### UC-UAAD-16: Unknown quota preserves deterministic order

```gherkin
Given quota state is missing, stale, or failed for one or more eligible candidates
And the available facts do not support a normalized comparison
When adaptive ranking evaluates the candidate set
Then deterministic role order is preserved
And uncertainty does not independently block dispatch or masquerade as healthy headroom
```

#### UC-UAAD-17: Adaptive explanation stays out of agent context

```gherkin
Given quota pressure changes the selected agent for an automatic request
When TeleClaude creates the selected runtime or answers an automated caller
Then quota diagnostics and human-facing fallback explanation are absent from agent context and machine responses
And a relevant human-facing CLI caller can reconcile the selected agent with quota pressure
```

## Known caveats

- Quota state never makes a degraded or unavailable agent eligible.
- Manual preference may choose through pressure only while the agent remains available
  under the deterministic contract.
- Unknown quota state is not healthy state. It preserves deterministic order when no
  sound comparison exists.
- One-shot safety is not caller-selectable. A provider path that cannot satisfy the
  no-session contract is refused instead of falling back to a model invocation.
