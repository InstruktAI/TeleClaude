---
description: Deterministic role- and availability-aware agent selection for every
  fresh session, with distinct manual-preference and fixed-continuation semantics.
---

# Role-Aware Agent Dispatch — Spec

## Required reads

@docs/local/spec/domain/agent_runtime.md

## What it is

Role-aware agent dispatch gives every fresh-session entry point one deterministic
agent-selection contract. A canonical command supplies the ordered candidates, configured
inventory and operator availability define eligibility, caller authority determines
whether an explicit agent is manual or automatic preference, and work already bound to
a runtime remains fixed.

The contract applies before agent-specific startup handling. Omission remains
automatic intent until selection, so equivalent fresh-session requests resolve the
same way regardless of which supported entry point creates them.

## Canonical fields

### Dispatch modes

**Automatic preference**
: Fresh work whose caller omits an agent, or whose system-role caller supplies a preferred
agent. A system-role preference is considered first but remains subject to automatic
eligibility. The canonical command
establishes the remaining ordered candidates. A scheduled job supplies its own ordered
candidates — its effective declaration's non-empty `agent` preference list — in place
of a command row. A job has no code-owned candidate order. An empty effective list
is rejected by the job configuration boundary before selection.
The routing decision identifies the job declaration as the candidate-order source
and retains the existing eligibility fallback or refusal reason.

**Manual preference**
: Fresh work where a caller without a system role explicitly selects an agent. The
selected agent must be known and enabled, and must not be operator-unavailable. A
degraded selected agent is honored because degradation gates automatic dispatch only.
An invalid manual selection is rejected; it never substitutes another agent.

**Fixed agent**
: Continuation work bound to an existing runtime or transcript. Fixed work never
substitutes another agent. A scheduled job is never fixed work: its declaration carries a
preference list, not a binding.

### Procedure dispatch declaration

Ordinary assignment work takes its automatic candidates and default thinking
mode from the entry procedure's `dispatch` declaration
(`general/spec/snippet-authoring-schema`): an ordered agent preference list
and one of `fast`, `med`, `slow`. Scheduled jobs instead receive their
candidate order and execution settings from the effective job declaration; a
job's declaration is never unioned with its procedure's. Role and job remain
identity facts and never participate in agent selection.

The global automatic order is Claude, Codex, Gemini, DeepSeek. It applies to
generic session creation with no procedure; an entry procedure without a
dispatch declaration is a publication defect and is refused before any session
exists. That rejection records one structured error without prompt or argument
content.

### Thinking-mode resolution

Run-session dispatch reads the same declaration. An explicit caller mode
overrides the procedure default. A doc-only commit review passes explicit
`med`.

Run-session mode resolution has one owner beside agent routing. Run-session
formatters, clients, and API models preserve omission and never independently
substitute `slow`; other session-creation contracts remain unchanged.

The result is an effective thinking mode, not a concrete model. Mapping that mode
to an ordered model chain, filtering model-scoped availability, and recovering from
model-specific quota exhaustion belong downstream and remain outside caller- and
job-policy-facing thinking-mode resolution.

### Eligibility and ordering

Automatic selection removes unconfigured, disabled, degraded, and unavailable
agents. Only operator status `available` is eligible. Reviewer selection uses that
same eligible ordered set without narrowing or reordering it by the agent used by an
initiating, producing, or earlier reviewer session. Reviewer independence comes from
the separately dispatched session and its review ownership, not from selecting a
different agent implementation.

Manual selection uses a distinct boundary for callers without a system role. A known,
enabled agent is manually selectable while available or degraded. Operator status
`unavailable` rejects the request. Manual rejection fails before session creation and
never enters automatic fallback ordering.

A system-role caller's explicit agent remains automatic preference. The candidate is
selected only while automatically eligible;
otherwise the resolver continues through the canonical command order. Degraded and
unavailable agents therefore remain reserved from automated dispatch even when an
automated caller names one explicitly.

An agent with no operator-availability row normalizes to available. An unexpired
degraded or unavailable row is ineligible, while an expired row normalizes back to
available under the existing availability contract. A storage read failure is not a
missing row and does not silently make the agent eligible; dispatch returns a distinct
availability-state failure before session creation.

Configuration iteration order never changes the result. When no eligible candidate
remains, fresh dispatch fails without creating a session.

### Explanation boundary

Relevant human-facing CLI callers receive the selected agent and the exact reason for
a fallback. Automated callers receive the selected agent and typed routing reason but
no human-facing routing explanation. Routing feedback never enters spawned-agent
startup context.

### Use cases

#### UC-RAAD-1: An operator can start procedure work on its declared agent

```gherkin
Given an operator starts fresh work through a procedure with an ordered agent preference
When TeleClaude selects the session agent
Then it uses the procedure's declared order among eligible agents
And configuration iteration order does not change the selection
```

#### UC-RAAD-3: Automatic eligibility is strict

#### UC-RAAD-4: Reviewer dispatch follows ordinary automatic ordering

```gherkin
Given an operator asks for an independent reviewer session
When TeleClaude selects the reviewer
Then it uses the ordinary automatic eligible order
And the initiating or producing agent does not change the reviewer selection
```

#### UC-RAAD-5: Generic work remains operable and deterministic

```gherkin
Scenario: Start generic work using the platform order
  Given an operator starts generic fresh work without an agent or procedure
  When TeleClaude selects the agent
  Then it uses Claude, Codex, Gemini, and DeepSeek in that order

Scenario: Refuse generic work when no agent is eligible
  Given an operator starts generic fresh work without an agent or procedure
  And no agent is eligible
  When TeleClaude resolves the request
  Then it reports a clear failure
  And no session or runtime is created
```

#### UC-RAAD-6: Manual agent selection never substitutes

```gherkin
Scenario: Honor a manual choice the operator can use
  Given an operator explicitly selects a known, enabled agent with available or degraded status
  When they start a fresh session
  Then TeleClaude selects exactly that agent

Scenario: Refuse an invalid manual choice
  Given an operator explicitly selects an unknown, disabled, or unavailable agent
  When they start a fresh session
  Then the request is rejected before session creation
  And TeleClaude does not substitute another agent
```

#### UC-RAAD-7: Fixed continuation never substitutes

```gherkin
Given an operator asks an existing session to continue on its already-bound agent
When that agent cannot continue without a handoff
Then TeleClaude does not select another agent
And the operator receives the continuation status or refusal for the bound agent
```

#### UC-RAAD-8: Every fresh-session entry point uses one policy

#### UC-RAAD-9: Omission remains automatic intent

#### UC-RAAD-10: An operator receives a clear failure when no agent is eligible

#### UC-RAAD-11: Human-facing fallback remains explainable

```gherkin
Given an operator requests fresh work and automatic selection uses a fallback agent
When the result is returned
Then the operator can see the selected agent and exact fallback reason
```

#### UC-RAAD-12: Routing explanation does not enter agent context

#### UC-RAAD-13: An operator can choose an explicit thinking mode

```gherkin
Scenario Outline: Explicit thinking mode overrides the declared mode
Given an operator starts a procedure session and chooses explicit thinking mode <mode>
And the procedure declares a default mode
When TeleClaude resolves the fresh-session request
Then the session uses the operator's explicit mode

Examples:
  | mode  |
  | fast  |
  | med   |
  | slow  |
```

#### UC-RAAD-14: An operator can run a procedure without choosing a mode

```gherkin
Scenario Outline: The procedure's declared mode resolves omission
Given an operator starts a procedure with declared thinking mode <mode>
And the operator omits a thinking mode
When TeleClaude resolves the request
Then the session uses the procedure's declared mode without asking the operator to choose

Examples:
  | mode  |
  | fast  |
  | med   |
  | slow  |
```

#### UC-RAAD-15: An operator can diagnose a procedure missing dispatch defaults

```gherkin
Given an operator attempts to start a published procedure that declares a role but no dispatch defaults
When TeleClaude resolves the request
Then the request is rejected before session creation as a publication defect naming the procedure
```

#### UC-RAAD-16: A resolved procedure supplies its declared mode

#### UC-RAAD-17: An automated caller's agent preference falls back when ineligible

#### UC-RAAD-18: Reviewer preference uses ordinary automatic eligibility

#### UC-RAAD-19: A job owner can select ordered agent preferences

```gherkin
Given an operator configures ordered agent preferences for a scheduled job
When the job is dispatched
Then TeleClaude selects from only those candidates in their declared order
And automatic eligibility rules apply and the result identifies declaration-sourced selection
And no eligible candidate results in an explicit refusal before session creation
```

#### UC-RAAD-20: A reviewer request excludes agents that already reviewed its target

#### UC-RAAD-21: No unreviewed candidate creates no session

#### UC-RAAD-22: A prior reviewer session's agent stays eligible for the same target

## Known caveats

- The prepare orchestrator normally performs intake, architecture, and planning inline.
  Those phases inherit the already selected runtime; their rows govern only fresh direct
  invocation.
- Manual preference and fixed continuation both preserve the selected agent. Manual
  preference validates a new selection and rejects it when invalid; fixed continuation
  reports whether an existing binding can continue.
- Quota collection and ranking extend this eligibility contract separately. They never
  make an agent eligible when this contract excludes it.
- A restart that asks for a handoff is the one continuation that may select a
  different agent. It runs this contract's fresh-session resolution for the
  session's command as it is, owns no eligibility or exclusion logic of its own,
  and is specified by `local/projects/teleclaude/spec/feature/agent_runtime/agent-handoff`.
