---
description: Preparation-view lifecycle actions target the project the cursor's row belongs to, and report the submitted operation's terminal outcome rather than its acceptance.
visibility: internal
delivered_by: [tui-start-routes-to-wrong-project]
---

# Preparation Lifecycle Actions — Spec

## What it is

The TUI Preparation view turns a keypress on a todo row into a lifecycle
operation against the daemon — prepare, start work, freeze, and the artifact
actions. Two properties make that operation trustworthy.

**The cursor's row names its own project.** A slug is unique only within a
project, so slug alone never identifies a todo across the fleet. The project a
lifecycle action targets is the one the cursor's row belongs to — the project
header the row sits under, falling back to the project the row itself carries.
No resolution consults a fleet-wide index keyed by slug, because such an index
cannot distinguish two projects that hold the same slug and would silently
substitute one for the other.

**Submission is not an outcome.** A lifecycle operation is durable and
asynchronous: the response to the submission is an acceptance receipt, and the
outcome exists only once the operation reaches a terminal state. A runner that
is not dispatched — a removed, delivered, iceboxed, or dependency-blocked
target, or a claim conflict — terminates the operation _successfully_ and
carries the refusal in the operation's result. The view therefore follows every
operation it submits to its terminal state and reports what it finds: a
not-dispatched or failed outcome reaches the operator at error severity
carrying the reported reason, never as a success message.

## Canonical fields

### Use cases

#### UC-PLA-1: Start-work targets the cursor's project and reports the operation's real outcome

```gherkin
Given two projects each hold a todo with the same slug
And the todo in the project the cursor is not under is soft-removed
And the cursor sits on the live todo under its own project header
When the operator starts work on the cursor's row
Then the lifecycle operation is submitted against the cursor's project
When a submitted lifecycle operation reaches a terminal state reporting the runner was not dispatched
Then the operator is notified at error severity
And the notification carries the operation's reported reason
```

## See Also

- docs/project/design/architecture/tui-state-layout.md — the Preparation view's
  interaction mapping and state model.
