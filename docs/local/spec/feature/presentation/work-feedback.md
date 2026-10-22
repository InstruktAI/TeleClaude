---
description: Deliberate work feedback in the TUI, with technical faults retained as
  ERROR diagnostics and operation outcomes remaining independently inspectable.
visibility: internal
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

Live runtime feedback is presented to current viewers without replaying obsolete
activity, lifecycle toasts or operation nudges after a delivery interruption.
Current state and recorded operation outcomes remain available through their
owning queries; diagnostic evidence retains its observability contract. This
presentation lifetime follows `general/policy/leadership` and
`local/projects/teleclaude/design/architecture/event-delivery`.

### Use cases

#### UC-WF1: An expected work refusal reaches the operator

```gherkin
Given a human operator requests an action in the TUI
When the action's owner refuses it with a deliberately published work explanation
Then the operator receives that explanation at error severity
And the notification states the owner's way forward when one is published
```

#### UC-WF2: A technical fault is diagnostic-only

#### UC-WF3: An unknown outcome retains its diagnostic address

#### UC-WF4: One outcome produces one work notification

#### UC-WF5: Technical failure counts produce no aggregate fallback

## Known caveats

- An unexpected fault can prevent a requested action without a toast. Its
  recorded operation outcome and diagnostic access remain available under
  their existing contracts.

## See Also

- docs/local/spec/feature/tui/preparation-lifecycle-actions.md
- docs/local/spec/feature/tui/daemon-connection-resilience.md
- docs/local/spec/feature/tui/notification-text-rendering.md
- docs/local/spec/feature/agent_runtime/durable-operation-outcomes.md
