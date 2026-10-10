---
description: Deliberate work feedback in the TUI, with technical faults retained as ERROR diagnostics and operation outcomes remaining independently inspectable.
visibility: internal
delivered_by:
  - quiet-technical-faults
---

# Work Feedback — Spec

## What it is

The TUI interrupts a human operator with deliberately published feedback about
expected work outcomes and refusals. The semantic owner of an outcome declares
its work message separately from its diagnostic error. Presentation consumes
that declaration without interpreting exception prose, response status,
exception ancestry or logging severity.

Unexpected technical faults are recorded at ERROR with their diagnostic context
and produce no toast, including a synthesized action-failure sentence, an
aggregate derived from caught failures or an outcome-unknown fallback. A
technical projection defect, hook defect, polling fault or local persistence
fault has the same diagnostic-only presentation. Catch-all exception handling
provides no work-feedback declaration.

The interruption boundary preserves human attention for relevant work outcomes
(`general/policy/leadership`). Diagnostic recording follows the observability
contract (`sdlc/policy/observability`). The recorded outcome remains truthful
when presentation is silent; existing operation records, terminal events,
caller delivery and view refresh retain their contracts
(`local/projects/teleclaude/design/architecture/operation-receipts`).

## Canonical fields

### Presentation boundary

Eligibility belongs to the outcome's deliberate work-feedback declaration.
An absent declaration produces no failure notification. The diagnostic error
remains available to its existing consumers. Expected refusals retain their
published explanation and sanctioned way forward, including readiness,
dependencies, live ownership, removal blockers, clearance and shutdown refusal.

The same boundary covers direct TUI actions, asynchronous operation following,
operation broadcasts, session-status notifications, media controls, project
adoption and local UI persistence. Existing intentional success feedback and
literal rendering retain their contracts. An eligible operation outcome is
presented once when more than one delivery path observes it.

Other adapters' presentation, notification subscriptions, recovery behavior
and the responsibilities of agents and the log bug hunter remain unchanged.

### Use cases

#### UC-WF1: An expected work refusal reaches the operator

```gherkin
Given a human operator requests an action in the TUI
When the action's owner refuses it with a deliberately published work explanation
Then the operator receives that explanation at error severity
And the notification states the owner's way forward when one is published
```

#### UC-WF2: A technical fault is diagnostic-only

```gherkin
Scenario Outline: Technical faults leave the operator's work uninterrupted by toasts
  Given a human operator is using the TUI
  When a technical fault occurs during <activity>
  Then the fault is recorded at ERROR with its diagnostic context
  And the operator receives no toast or synthesized failure notification for it

  Examples:
    | activity                              |
    | a background operation                |
    | a requested action                    |
    | a session close                       |
    | operation observation                 |
    | a hook                                |
    | local media or preference persistence |
    | projecting a todo's durable identity  |
```

#### UC-WF3: An unknown outcome retains its diagnostic address

```gherkin
Given a human operator has submitted an asynchronous action from the TUI
When the TUI reaches its observation bound without establishing the outcome
Then the observation condition is recorded at ERROR with the operation's identity
And the existing receipt remains available for outcome inspection
And the operator receives no outcome-unknown or retry-instruction toast
```

#### UC-WF4: One outcome produces one work notification

```gherkin
Given an asynchronous action publishes eligible work feedback for a human TUI operator
When both live delivery and operation observation report the same outcome
Then the operator receives its work notification once
```

#### UC-WF5: Technical failure counts produce no aggregate fallback

```gherkin
Given a human operator requests an action for several sessions in the TUI
When unexpected technical faults affect some of those requests
Then their diagnostics are recorded at ERROR
And the operator receives no aggregate notification derived from those technical failures
```

## Known caveats

- An unexpected fault can prevent a requested action without a toast. Its
  recorded operation outcome and diagnostic access remain available under
  their existing contracts.

## See Also

- docs/local/spec/feature/tui/preparation-lifecycle-actions.md
- docs/local/spec/feature/tui/daemon-connection-resilience.md
- docs/local/spec/feature/tui/notification-text-rendering.md
- docs/local/spec/feature/agent_runtime/durable-operation-outcomes.md
