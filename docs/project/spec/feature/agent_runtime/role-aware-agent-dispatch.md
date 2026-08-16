---
description: Deterministic role- and availability-aware agent selection for every fresh session, with distinct manual-preference and fixed-continuation semantics.
delivered_by:
  - deterministic-agent-routing
---

# Role-Aware Agent Dispatch — Spec

## Required reads

@docs/project/spec/domain/agent_runtime.md

## What it is

Role-aware agent dispatch gives every fresh-session entry point one deterministic
agent-selection contract. A job role supplies the ordered candidates, configured
inventory and operator availability define eligibility, explicit human selection is
a bounded manual preference, and work already bound to a runtime remains fixed.

The contract applies before agent-specific startup handling. Omission remains
automatic intent until selection, so equivalent fresh-session requests resolve the
same way regardless of which supported entry point creates them.

## Canonical fields

### Dispatch modes

**Automatic preference**
: Fresh work whose caller has not selected an agent. The job role and, for prepare
orchestration, todo kind establish the ordered candidates.

**Manual preference**
: Fresh work where a human explicitly selects an agent. The selected agent must be
known, enabled, and operator-available. Otherwise the request is rejected or falls
back through the applicable deterministic order.

**Fixed agent**
: Continuation work bound to an existing runtime, transcript, or declared fixed-agent
job. Fixed work never substitutes another agent.

### Automatic role preferences

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

The global automatic order is Claude, Codex, Gemini. It applies when role context is
absent or unmapped. A known role missing from the matrix uses the same order while
surfacing a policy defect.

### Eligibility and ordering

Automatic selection removes unconfigured, disabled, degraded, and unavailable
agents. Only operator status `available` is eligible. Reviewer selection then prefers
an eligible agent different from the producer while preserving the applicable row's
relative order. The producer remains eligible when no independent candidate survives.

An agent with no operator-availability row normalizes to available. An unexpired
degraded or unavailable row is ineligible, while an expired row normalizes back to
available under the existing availability contract. A storage read failure is not a
missing row and does not silently make the agent eligible; dispatch returns a distinct
availability-state failure before session creation.

Configuration iteration order never changes the result. When no eligible candidate
remains, fresh dispatch fails without creating a session.

### Explanation boundary

Relevant human-facing CLI callers receive the selected agent and the exact reason for
a fallback. Spawned agents and automated callers receive no human-facing routing
explanation in startup context or machine responses; they receive only the selected
agent or the typed failure required by their contract.

### Use cases

#### UC-RAAD-1: Automatic dispatch follows the complete role policy

```gherkin
Given an agent caller creates fresh work without selecting an agent
And the work has a canonical job role
When TeleClaude selects the session agent
Then the initial candidate order is the complete row for that role
And configuration iteration order does not change the result
```

#### UC-RAAD-2: Prepare selection uses todo kind

```gherkin
Given an agent caller creates a fresh prepare orchestrator
When the todo kind is feature
Then the ordered candidates are Claude, Codex, Gemini
When the todo kind is change or bug
Then the ordered candidates are Codex, Claude, Gemini
```

#### UC-RAAD-3: Automatic eligibility is strict

```gherkin
Given an automatic fresh-session request has an ordered candidate set
When TeleClaude evaluates eligibility
Then unconfigured, disabled, degraded, and unavailable agents are excluded
And only an operator-available agent may be selected
```

#### UC-RAAD-4: Reviewer independence preserves eligibility and order

```gherkin
Given an agent caller creates a fresh reviewer session
And an eligible candidate differs from the producer
When TeleClaude selects the reviewer
Then the independent candidate is preferred without promoting an ineligible agent
And the role row's relative order is otherwise preserved
And the producer may review when no independent eligible candidate remains
```

#### UC-RAAD-5: Unmapped work remains operable and deterministic

```gherkin
Given an agent caller creates fresh work with absent or unmapped role context
When TeleClaude selects the session agent
Then it uses Claude, Codex, Gemini in that order
And a known role missing from the matrix is surfaced as a policy defect
```

#### UC-RAAD-6: Manual preference respects eligibility

```gherkin
Given a human explicitly selects an agent for a fresh session
When the selected agent is known, enabled, and available
Then TeleClaude selects that agent
When the selected agent is degraded or unavailable
Then TeleClaude falls back through the applicable deterministic order
And the human-facing caller receives the fallback reason
When the selected agent is unknown or disabled
Then the request is rejected
```

#### UC-RAAD-7: Fixed continuation never substitutes

```gherkin
Given an agent caller resumes, revives, restarts, attaches, or continues work bound to a runtime
Or a job declares a fixed agent
When the bound agent cannot continue
Then TeleClaude does not select a different agent
And the caller receives an agent-specific refusal or continuation status
```

#### UC-RAAD-8: Every fresh-session entry point uses one policy

```gherkin
Given two agent callers create equivalent fresh-session requests through different supported entry points
And role, todo kind, configured inventory, enabled state, operator status, and explicit-or-omitted intent are equal
When TeleClaude selects each session agent
Then both requests select the same agent or return the same eligibility failure
```

#### UC-RAAD-9: Omission remains automatic intent

```gherkin
Given a fresh-session request omits the agent
When the request crosses client, adapter, or lifecycle boundaries
Then omission remains distinguishable from an explicit human selection until policy evaluation
And the created session reports the agent TeleClaude selected
```

#### UC-RAAD-10: No eligible candidate creates no session

```gherkin
Given a fresh-session request has no eligible agent
When TeleClaude resolves the request
Then the request fails clearly
And no session or runtime is created
```

#### UC-RAAD-11: Human-facing fallback remains explainable

```gherkin
Given TeleClaude selects a fallback for a fresh human-facing CLI request
When the result is returned
Then the human caller can see the selected agent and exact fallback reason
```

#### UC-RAAD-12: Routing explanation does not enter agent context

```gherkin
Given TeleClaude selects an agent for an automated or spawned fresh-session request
When the request reaches the selected runtime
Then human-facing routing explanation is absent from startup context and machine responses
And the caller receives only the selected agent or required typed failure
```

## Known caveats

- The prepare orchestrator normally performs intake, architecture, and planning inline.
  Those phases inherit the already selected runtime; their rows govern only fresh direct
  invocation.
- Manual preference and fixed continuation are intentionally different. Manual preference
  may fall back inside the fresh-session boundary; fixed continuation never does.
- Quota collection and ranking extend this eligibility contract separately. They never
  make an agent eligible when this contract excludes it.
