---
description: Where a computer gets the todos of a project another computer serves — a
  project on the GitHub workflow store from GitHub itself, through the computer's own
  workflow store and only while something consumes them, and a project on the local
  store from the computer that keeps it.
visibility: internal
delivered_by:
  - redis-claim-check-external-content
---

# Fleet Todo Reads — Spec

## Required reads

- @docs/local/spec/domain/workflow.md

## What it is

Every computer of a fleet shows the todos of projects other computers serve as
well as its own. Where a computer gets them depends on where the project keeps
its todos:

- **A project on the local workflow store** keeps its todos on the computer
  that serves it, and that computer's workflow store is the only source of
  them. How they reach its peers is
  `local/projects/teleclaude/design/architecture/redis-transport`.
- **A project on the GitHub workflow store** keeps its todos on GitHub. Every
  computer reads them from GitHub through its own workflow store
  (`local/projects/teleclaude/design/architecture/workflow-store`), whichever
  computers serve the project. No computer's workflow store is the source of
  another computer's read of them.

A computer reads a GitHub-backed project's todos from GitHub to show them only
while something consumes them: an explicit read, such as a view being opened or
an agent listing them, or a view subscribed to todo or project changes. While a
subscription is held, a change GitHub holds for those todos reaches the
subscribed view without another explicit read. Without one, nothing is read
until the next explicit read. The workflow store's own upkeep of the projects a
computer serves stays as the workflow store defines it.

A read of todos that have not changed on GitHub since the computer last read
them revalidates that read instead of fetching the todos again. A computer reads
one GitHub repository once, however many of its peers serve the project.

When GitHub cannot be read, the read says that the project's todos cannot be
read from GitHub, and why. It never shows another computer's copy in their
place.

## Canonical fields

- **Where a project's todos come from.** The local workflow store: the computer
  that serves the project. The GitHub workflow store: GitHub, read by each
  computer for itself.
- **Consumer.** An explicit read, or a held subscription to todo or project
  changes. A computer with neither reads nothing from GitHub to show todos.
- **Unreadable source.** The read says so and why; no other computer's copy
  stands in.

### Use cases

#### UC-FTR1: An operator sees a GitHub-backed project's todos as GitHub holds them, from any computer

```gherkin
Scenario: The todos shown are the ones GitHub holds
  Given a project whose todos are kept on GitHub
  And an operator at any computer of the fleet
  When the operator views the project's todos
  Then the operator sees the todos GitHub holds for the project

Scenario: GitHub cannot be read
  Given a project whose todos are kept on GitHub
  And GitHub cannot be read from the operator's computer
  When the operator views the project's todos
  Then the operator is told the todos cannot be read from GitHub, and why
  And no other computer's copy of them is shown
```

## Known caveats

- A read addressed to another computer — a todo listing that names that
  computer, or a file opened from a row under it — is answered by that
  computer, as `local/projects/teleclaude/spec/feature/integration/computer-addressed-execution`
  defines, and carries back what that computer read.
- A computer reads a GitHub-backed project's todos only as the GitHub App the
  project's store declaration names; a computer without that App says the todos
  cannot be read.
