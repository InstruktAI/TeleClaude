---
description: Deterministic role- and availability-aware agent selection for every
  fresh session, with distinct manual-preference and fixed-continuation semantics.
---

# Role-Aware Agent Dispatch — Spec

## Required reads

@docs/project/spec/domain/agent_runtime.md

## What it is

Role-aware agent dispatch gives every fresh-session entry point one deterministic
agent-selection contract. A canonical command supplies the ordered candidates, configured
inventory and operator availability define eligibility, explicit human selection is
a bounded manual preference, and work already bound to a runtime remains fixed.

The contract applies before agent-specific startup handling. Omission remains
automatic intent until selection, so equivalent fresh-session requests resolve the
same way regardless of which supported entry point creates them.

## Canonical fields

### Dispatch modes

**Automatic preference**
: Fresh work whose caller has not selected an agent. The canonical command and, for prepare
orchestration, todo kind establish the ordered candidates.

**Manual preference**
: Fresh work where a human explicitly selects an agent. The selected agent must be
known and enabled, and must not be operator-unavailable. A degraded selected agent is
honored because degradation gates automatic dispatch only. An invalid manual
selection is rejected; it never substitutes another agent.

**Fixed agent**
: Continuation work bound to an existing runtime, transcript, or declared fixed-agent
job. Fixed work never substitutes another agent.

### Command dispatch policy

One command-keyed matrix owns automatic agent selection and the default thinking
mode. System role and job role remain separate session-identity and authority facts;
neither selects an agent or mode.

| Command                     | Ordered agents                                                    | Default thinking mode |
| --------------------------- | ----------------------------------------------------------------- | --------------------- |
| `analyze-todo-input`        | Claude, Codex, Gemini                                             | `slow`                |
| `next-build`                | Codex, Claude, Gemini                                             | `med`                 |
| `next-review-build`         | Codex, Claude, Gemini                                             | `slow`                |
| `next-review-prd`           | Codex, Claude, Gemini                                             | `slow`                |
| `next-review-plan`          | Codex, Claude, Gemini                                             | `slow`                |
| `next-review-architecture`  | Codex, Claude, Gemini                                             | `slow`                |
| `next-review-commits`       | Codex, Claude, Gemini                                             | `med`                 |
| `next-finalize`             | Gemini, Claude, Codex                                             | `fast`                |
| `next-prepare-intake`       | Claude, Codex, Gemini                                             | `slow`                |
| `next-prepare-architecture` | Claude, Codex, Gemini                                             | `slow`                |
| `next-prepare-diagnose`     | Codex, Claude, Gemini                                             | `med`                 |
| `next-prepare-plan`         | Claude, Codex, Gemini                                             | `slow`                |
| `next-prepare-task`         | Claude, Codex, Gemini                                             | `med`                 |
| `next-emulate-po`           | Claude, Gemini, Codex                                             | `med`                 |
| `next-drift-analyze`        | Codex, Claude, Gemini                                             | `fast`                |
| `next-prepare`              | feature: Claude, Codex, Gemini; change/bug: Codex, Claude, Gemini | `slow`                |
| `next-work`                 | Codex, Claude, Gemini                                             | `med`                 |
| `next-run-task`             | Codex, Claude, Gemini                                             | `med`                 |
| `next-integrate`            | Codex, Claude, Gemini                                             | `slow`                |
| `next-coordinate`           | Claude, Codex, Gemini                                             | `slow`                |
| `next-create`               | Claude, Codex, Gemini                                             | `med`                 |
| `next-create-art`           | Gemini, Claude, Codex                                             | `med`                 |
| `next-create-html`          | Gemini, Claude, Codex                                             | `med`                 |
| `next-defer`                | Claude, Codex, Gemini                                             | `slow`                |

The global automatic order is Claude, Codex, Gemini. It applies to generic session
creation with no canonical command; a known command missing from this matrix is a
policy defect.

### Thinking-mode resolution

Run-session dispatch reads the same command matrix. An explicit caller mode
overrides the command default. `/next-review-commits` resolves to `med` when its
caller omits the mode; a doc-only commit review passes explicit `fast`.

When a run-session request has no command-matrix row and no explicit thinking mode,
it is rejected before session creation with feedback to assess the work and retry
with `fast`, `med`, or `slow`. Caller system role does not participate in
thinking-mode resolution.

Run-session mode resolution has one owner beside agent routing. Run-session
formatters, clients, and API models preserve omission and never independently
substitute `slow`; other session-creation contracts remain unchanged.

The result is an effective thinking mode, not a concrete model. Mapping that mode
to an ordered model chain, filtering model-scoped availability, and recovering from
model-specific quota exhaustion belong downstream and remain outside caller- and
job-policy-facing thinking-mode resolution.

### Eligibility and ordering

Automatic selection removes unconfigured, disabled, degraded, and unavailable
agents. Only operator status `available` is eligible. Reviewer selection then prefers
an eligible agent different from the producer while preserving the applicable row's
relative order. The producer remains eligible when no independent candidate survives.

Manual selection uses a distinct boundary. A known, enabled agent is manually
selectable while available or degraded. Operator status `unavailable` rejects the
request. Manual rejection fails before session creation and never enters automatic
fallback ordering.

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

#### UC-RAAD-1: Automatic dispatch follows the complete command policy

```gherkin
Given an agent caller creates fresh work without selecting an agent
And the work has a canonical command-matrix row
When TeleClaude selects the session agent
Then the initial candidate order is the complete row for that command
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
Given an agent caller creates a fresh reviewer-command session
And an eligible candidate differs from the producer
When TeleClaude selects the reviewer
Then the independent candidate is preferred without promoting an ineligible agent
And the command row's relative order is otherwise preserved
And the producer may review when no independent eligible candidate remains
```

#### UC-RAAD-5: Unmapped work remains operable and deterministic

```gherkin
Given an agent caller creates generic fresh work with no canonical command
When TeleClaude selects the session agent
Then it uses Claude, Codex, Gemini in that order
And a known command missing from the matrix is surfaced as a policy defect
```

#### UC-RAAD-6 (r2): Manual agent selection never substitutes

```gherkin
Given a human explicitly selects an agent for a fresh session
When the selected agent is known and enabled
And its operator status is available or degraded
Then TeleClaude selects exactly that agent
When the selected agent is unavailable, unknown, or disabled
Then the request is rejected before session creation
And TeleClaude does not substitute another agent
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
And command, todo kind, configured inventory, enabled state, operator status, and explicit-or-omitted intent are equal
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

#### UC-RAAD-13: Explicit thinking mode overrides command policy

```gherkin
Scenario Outline: Explicit thinking mode overrides configured command mode
Given an authenticated <caller kind> caller invokes sessions run with an explicit valid thinking mode
And the command has a configured thinking mode
When TeleClaude resolves the fresh-session request
Then the explicit thinking mode is used

Examples:
  | caller kind |
  | human       |
  | agent       |
```

#### UC-RAAD-14: A command mode resolves caller omission

```gherkin
Scenario Outline: Configured command mode resolves omission
Given an authenticated <caller kind> caller invokes sessions run for a command with a configured thinking mode
And its caller omits a thinking mode
When TeleClaude resolves the request
Then the configured command mode is used
And the session is created without asking the caller to choose

Examples:
  | caller kind |
  | human       |
  | agent       |
```

#### UC-RAAD-15: Work outside the command matrix requires an explicit thinking mode

```gherkin
Given a caller invokes sessions run for work with no command-matrix row
And the caller omits a thinking mode
When TeleClaude resolves the request
Then the request is rejected before session creation
And the caller is told to assess the work and retry with a supported thinking mode
And one structured ERROR records thinking_mode_required without prompt or command-argument content
```

#### UC-RAAD-16: A recognized command resolves its matrix mode

```gherkin
Given a caller invokes sessions run for work whose recognized command has a matrix entry
And the caller omits a thinking mode
When TeleClaude resolves the request
Then TeleClaude uses that command's matrix thinking mode
And the selected agent's corresponding model chain resolves the launch model
And caller system role does not change the result
```

## Known caveats

- The prepare orchestrator normally performs intake, architecture, and planning inline.
  Those phases inherit the already selected runtime; their rows govern only fresh direct
  invocation.
- Manual preference and fixed continuation both preserve the selected agent. Manual
  preference validates a new selection and rejects it when invalid; fixed continuation
  reports whether an existing binding can continue.
- Quota collection and ranking extend this eligibility contract separately. They never
  make an agent eligible when this contract excludes it.
