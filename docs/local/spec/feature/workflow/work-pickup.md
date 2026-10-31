---
description: The platform takes up a project's work on its own when something that decides it changes — a local todo change, a session ending, another computer's or GitHub's change reaching the record, a pickup setting, a scheduled time, a failed start's retry — for that project only, and never on a periodic scan.
delivered_by:
  - event-driven-lifecycle-runner
---

# Work Pickup — Spec

## What it is

Work pickup is how a project's work starts without a person starting it: the
lifecycle runner evaluates the project's todos and starts an orchestrator for
each one that is ready. Which todos are ready, and how many may run, is decided
by the lifecycle state machines and the project's workflow settings
(`local/projects/teleclaude/design/architecture/lifecycle-state-machines`); who
may start an orchestrator is decided by driver admission
(`local/projects/teleclaude/spec/feature/workflow/driver-admission`). This spec
states when pickup evaluates a project: when something it decides on changed,
for the project it changed in, and at no other time.

**Business value:** work a person makes ready is taken up as soon as the change
is known, whether it was made on this computer, on another one or on GitHub,
and a fleet where nothing is happening spends nothing on pickup.

## Canonical fields

### Where pickup runs

A project's pickup runs on the computer that drives its work: for a project on
the GitHub workflow store, its active computer (driver-admission); for any
other project, each computer that holds a checkout of it. Each evaluation
concerns one project.

### What wakes pickup

Pickup evaluates a project when one of these happens:

- **A change to its work on this computer** that can make a todo startable: a
  todo created for pickup; a todo updated, including hold, release, schedule,
  dependency, kind and group; a phase advanced; a human gate approved; a todo
  delivered, removed or reactivated; a claim released or cleared, including a
  release another computer asks this computer to make.
- **A session ending** that worked in the project's checkout.
- **A change made elsewhere reaching this computer.** For a project on the
  GitHub workflow store, a change another computer makes to the project's
  work record reaches the active computer when GitHub delivers the
  repository's webhook for it
  (`local/projects/teleclaude/spec/feature/integration/github-webhook-normalization`);
  adopting it into this computer's copy of the record
  (`local/projects/teleclaude/design/architecture/workflow-store`) wakes
  pickup as the same change made here would. A person's change on an item's
  issue that becomes a workflow act
  (`local/projects/teleclaude/spec/feature/integration/github-work-control`)
  is a change to the work on the computer that takes the act.
- **A pickup setting changing:** whether pickup runs, which kinds of work it
  starts, and how many todos it drives at once. Every project the setting
  governs is evaluated.
- **This computer becoming the project's active computer:** when the notice
  of its naming arrives and the variable names it, or, when it does not yet,
  once the naming can no longer change the variable and it then does.
- **A scheduled task coming due:** its one-shot instant, or each occurrence of
  its recurring rule.
- **A start pickup made failing** without its orchestrator starting: pickup
  evaluates the todo again within a minute, for as long as it stays startable.
- **A claim held only because a computer did not answer** whether its session
  still drives the todo: the active computer evaluates the project again
  within a minute, for as long as that computer does not answer.
- **A pass that fails:** pickup evaluates the project again within a minute.
- **A claim whose session has ended** — or whose start gave up after its claim
  was recorded — once the session's computer answers that the session no
  longer drives the todo: the claim is cleared and the todo evaluated, without
  waiting for another change to it.

Pickup evaluates the project within seconds of its change being known on this
computer, and a change made elsewhere is known on the active computer within
seconds of GitHub delivering its webhook. That evaluation starts each todo it
finds ready that the project's capacity and driver admission let it start; a
todo they hold back waits for the change that frees it, and a start that fails
is retried as above. Work that became startable while the daemon was stopping,
stopped or starting is taken up once the daemon runs again.

### What does not wake pickup

Nothing else. With no change of the kinds above, pickup does not run and reads
no project's work.

## Known caveats

- While GitHub holds a project's requests back after a rate limit, a delivered
  change is adopted, and its work evaluated, only when GitHub's stated time has
  passed (`local/projects/teleclaude/design/architecture/workflow-store`).
- A change made elsewhere that GitHub does not deliver reaches the active
  computer only when its copy of the record is next brought up to date by
  another delivery or by the store's own refresh; pickup does not look for it.
- An occurrence of a recurring task that falls while the daemon is not running
  is not caught up; the task runs at its next occurrence.
