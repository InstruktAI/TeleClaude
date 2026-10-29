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
- **A project on the GitHub workflow store** keeps its repository work on
  GitHub: every item the store publishes there, with its artifacts. Every
  computer reads that from GitHub through its own workflow store
  (`local/projects/teleclaude/design/architecture/workflow-store`), whichever
  computers serve the project, and also when the read names another computer.
  No computer's workflow store is the source of another computer's read of it.
  The project's items that are not repository work — tasks and creative-track
  work — the store keeps only on the computer that holds them
  (`local/projects/teleclaude/adr/0126-non-repository-work-stays-in-the-github-store-working-copy`),
  so that computer is their only source, as for a project on the local store.

A computer reads a GitHub-backed project's repository work from GitHub to show
it only while something consumes it: an explicit read, such as a view being opened or
an agent listing it, or a view subscribed to todo or project changes. While a
subscription is held, a change GitHub holds for that work reaches the
subscribed view without another explicit read. Without one, nothing is read
until the next explicit read. The workflow store's own upkeep of the projects a
computer serves stays as the workflow store defines it.

A read of repository work that has not changed on GitHub since the computer
last read it revalidates that read instead of fetching it again. A computer reads
one GitHub repository once, however many of its peers serve the project.

When GitHub cannot be read, the read says that the project's repository work
cannot be read from GitHub, and why. A computer that has read that work from
GitHub before shows its last read, marked as not current; one that never has
shows nothing in its place. It never shows another computer's copy.

## Canonical fields

- **Where a project's todos come from.** The local workflow store: the computer
  that serves the project. The GitHub workflow store: GitHub for repository work
  and its artifacts, read by each computer for itself; the holding computer for
  tasks and creative-track work.
- **Consumer.** An explicit read, or a held subscription to todo or project
  changes. A computer with neither reads nothing from GitHub to show todos.
- **Unreadable source.** The read says so and why. The computer's own last read
  from GitHub stays shown, marked as not current; no other computer's copy
  stands in.

### Use cases

#### UC-FTR1: An operator sees a GitHub-backed project's repository work as GitHub holds it, from any computer

```gherkin
Scenario: The repository work shown is what GitHub holds
  Given a project on the GitHub workflow store
  And an operator at any computer of the fleet
  When the operator views the project's repository work
  Then the operator sees the repository work GitHub holds for the project

Scenario: GitHub cannot be read
  Given a project on the GitHub workflow store
  And GitHub cannot be read from the operator's computer
  When the operator views the project's repository work
  Then the operator is told that work cannot be read from GitHub, and why
  And what the operator's computer last read from GitHub is shown as not current
  And no other computer's copy of it is shown
```

## Known caveats

- A computer reads a GitHub-backed project's repository work only as the GitHub
  App the project's store declaration names; a computer without that App says
  that work cannot be read.
