---
description: An admin switches a project from its local todo store to the GitHub store
  with one command that also moves the project's open work into its repository, and
  can be run again until the move is complete.
---

# GitHub Store Switch — Spec

## Required reads

- @docs/local/spec/domain/workflow.md
- @docs/local/spec/feature/workflow/github-work-record.md

## What it is

The behavioral contract for `telec todo switch-to-github`: an admin, or an
agent session acting for one, switches the project that holds the current
directory from the local workflow store to the GitHub store and moves the
project's open work items into its repository, where the GitHub work record
(`local/projects/teleclaude/spec/feature/workflow/github-work-record`) holds
them from then on.

**Business value:** a project that adopts the GitHub work record keeps the work
it still intends to do instead of starting empty, and its collaborators find
every open item on GitHub with the history it was prepared under.

The switch is one-way. The command never moves anything back to the local
store, and once the project selects GitHub no workflow command writes the local
store again: it stays on the computer, frozen, with every record it held.

## Canonical fields

### Reach

Admin only — an admin at a terminal, or a session an admin started without an
agent role. A session carrying an agent role is refused
(`local/projects/teleclaude/design/cli-authorization-matrix`).

### Readiness

The project declares the repository and platform App for the GitHub store
(`local/projects/teleclaude/spec/teleclaude-config`), and that App can obtain
issue write access to the repository. When either fails, the run refuses with
the missing fact and changes nothing.

### Quiet work

While the project still selects the local store, the run refuses when any open
item is claimed by a live session, bound to a live session or to a running
operation other than this run, ready for integration (which includes a
candidate the integrator parked), or being integrated, and when the integrator
is working a candidate. The refusal names each such item and what holds it,
and changes nothing. Between this check and the switch, no workflow change
commits to the local store and the integrator starts no candidate.

### Switch

The run sets the project's declared store to `github`. From then on every
workflow command on the project reads and writes the GitHub store, and the
move fills it.

### What moves

Every active and iceboxed item moves, together with every holder a moved item
is grouped under. Each moved item keeps its identity, creation record, workflow
state, dependencies and every version of every artifact with its digest,
writer and time, so approvals and review stamps bound to a digest still hold.

Delivered and removed items stay in the local store. A moved item grouped
under a delivered or removed item moves without that membership: on GitHub it
lists without that parent, and the parent's slug no longer resolves to it as a
group, while the item itself is prepared and worked by its own slug as before.
A dependency on an item that does not move is not carried, because that item
is delivered, removed, or a holder with no open member, and so already
satisfies it.

Every commit review and documentation transfer the local store holds moves to
the repository's project records, because the workflow reads them as evidence
for the commits and documentation it checks.

<!-- planned:github-issue-projection -->

A task, and an item on the creative track, is not repository work
(`local/projects/teleclaude/spec/feature/workflow/github-work-record`): the run
carries it into the GitHub store as work kept on this computer, with the same
identity, state and history, and publishes nothing of it to the repository.
<!-- /planned:github-issue-projection -->

### Order and atomicity

Each item reaches GitHub whole or not at all, after every holder it is grouped
under. Until a dependency it names has been moved, an item is not ready for
work, as with any unsatisfied dependency.

### Repeatable

A run writes only what the GitHub store lacks. An item the GitHub store
already holds, and a project record already present, are skipped. A run on a
project that already selects GitHub skips the quiet-work check and continues
the move from the frozen local store. A run that finds nothing left to move
reports the move complete.

### Slug conflicts

An item whose slug the GitHub store already gives to a different item is not
moved and is reported with both identities.

### Stopping

A GitHub refusal, such as a rate limit or an unavailable service, stops the
run. Everything already moved stays moved, and the next run continues from
there.

### Outcome report

<!-- planned-change:github-issue-projection -->

The command returns a receipt for the run, and the run's outcome is read from
that operation. The report lists the items moved, already present, moved
without a finished group, and not moved with their reasons; the project
records moved; the cause of a refusal or stop; and whether the move is
complete. The operation fails when the run refused, stopped, or left an item
unmoved, and completes otherwise.
<!-- change:github-issue-projection -->

The command returns a receipt for the run, and the run's outcome is read from
that operation. The report lists the items moved, already present, moved
without a finished group, kept on this computer, and not moved with their
reasons; the project records moved; the cause of a refusal or stop; and
whether the move is complete. The operation fails when the run refused,
stopped, or left an item unmoved, and completes otherwise.
<!-- /planned-change:github-issue-projection -->

### Use cases

#### UC-GSS1: Switch a project and move its open work

```gherkin
Given a project on the local store with active and iceboxed items
And its declared platform App can write issues in its declared repository
And none of its open items is claimed, worked on, or with the integrator
When an admin switches the project to GitHub
Then the project selects the GitHub store
And every active and iceboxed item is an issue in the repository with its state and every artifact version
And the run's outcome reports the move complete
```

#### UC-GSS2: Refused while work is in flight

```gherkin
Given a project on the local store with an item claimed by a live session
When an admin switches the project to GitHub
Then the run is refused naming that item and its claimant
And the project still selects the local store
And nothing was written to the repository
```

#### UC-GSS3: Continue an interrupted move

```gherkin
Given a project switched to GitHub whose move stopped on a GitHub rate limit
When the admin runs the switch again after the limit has passed
Then the items already moved are skipped
And the remaining open items are moved
And no item exists twice in the repository
```

## Known caveats

- Delivered and removed items stay only in the frozen local store, and no
  workflow command reads that store once the project selects GitHub.
- The move reads the local store of the computer it runs on. Another
  computer's local store of the same project is not moved.
- A workflow write already under way when the switch takes effect can still
  land in the frozen local store. A later run moves an item created that way,
  but not a later change to an item it already moved.
- GitHub limits how quickly content may be created. The move spaces its writes
  to stay within those limits, so moving a large store takes hours, and while
  it runs, workflow writes to the project's repository from the same computer
  are spaced the same way.
- While the move publishes an item, which takes seconds for most items and
  up to a few minutes for the largest, a workflow write on the project can
  fail as busy. It changes nothing and succeeds when repeated.
- Moved items, with every artifact version, become readable to everyone who
  can read the repository.
