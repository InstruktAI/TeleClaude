---
description: An admin switches a project from its local todo store to the GitHub store with one command that also moves the project's open work into its repository, and can be run again until the move is complete.
delivered_by:
  - github-store-switch
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
store, and once the project selects GitHub nothing writes the local store
again: it stays on the computer, frozen, with every record it held.

## Canonical fields

- **Reach:** admin only — an admin at a terminal, or a session an admin
  started without an agent role. A session carrying an agent role is refused
  (`local/projects/teleclaude/design/cli-authorization-matrix`).
- **Readiness:** the project declares the repository and platform App for the
  GitHub store (`local/projects/teleclaude/spec/teleclaude-config`), and that
  App can obtain issue write access to the repository. When either fails, the
  command refuses with the missing fact and changes nothing.
- **Quiet work:** while the project still selects the local store, the command
  refuses when any open item is claimed by a live session, bound to a live
  session or a running operation, ready for integration or being integrated,
  or parked by the integrator. The refusal names each such item and what holds
  it, and changes nothing. No workflow change commits to the local store
  between this check and the switch.
- **Switch:** the command sets the project's declared store to `github`. From
  then on every workflow command on the project reads and writes the GitHub
  store, and the move below fills it.
- **What moves:** every active and iceboxed item, and every item a moved item
  is grouped under whatever its status, so group membership is kept. Each
  moved item keeps its identity, creation record, workflow state, dependencies
  and every version of every artifact with its digest, writer and time, so
  approvals and review stamps bound to a digest still hold. A dependency on an
  item that does not move is not carried: such an item is delivered, removed,
  or a group whose members are all delivered or removed, and so already
  satisfies it. Every commit review and documentation transfer the local store
  holds moves to the repository's project records, because the workflow reads
  them as evidence for the commits and documentation it checks.
- **Order and atomicity:** each item reaches GitHub whole or not at all, after
  every moved item it is grouped under or depends on.
- **Repeatable:** a run writes only what the GitHub store lacks. An item the
  GitHub store already holds, and a project record already present, are
  skipped. Running the command on a project that already selects GitHub skips
  the quiet-work check and continues the move from the frozen local store. A
  run that finds nothing left to move reports the move complete.
- **Slug conflicts:** an item whose slug the GitHub store already gives to a
  different item is not moved and is reported with both identities.
- **Stopping:** a GitHub refusal, such as a rate limit or an unavailable
  service, stops the run. Everything already moved stays moved, and the next
  run continues from there.
- **Outcome report:** the items moved, already present, and not moved with
  their reasons; the project records moved; the cause of a stop; and whether
  the move is complete. The command exits unsuccessfully when it refused,
  stopped, or left an item unmoved.

### Use cases

#### UC-GSS1: Switch a project and move its open work

```gherkin
Given a project on the local store with active and iceboxed items
And its declared platform App can write issues in its declared repository
And none of its open items is claimed, worked on, or with the integrator
When an admin switches the project to GitHub
Then the project selects the GitHub store
And every active and iceboxed item is an issue in the repository with its state and every artifact version
And the admin sees the move reported complete
```

#### UC-GSS2: Refused while work is in flight

```gherkin
Given a project on the local store with an item claimed by a live session
When an admin switches the project to GitHub
Then the switch is refused naming that item and its claimant
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

- Delivered and removed items, other than group parents of moved items, stay
  only in the frozen local store, and no workflow command reads that store once
  the project selects GitHub.
- The move reads the local store of the computer it runs on. Another
  computer's local store of the same project is not moved.
- A workflow write already under way when the switch takes effect can still
  land in the frozen local store. A later run moves an item created that way,
  but not a later change to an item it already moved.
- GitHub limits how quickly content may be created, so moving a large store
  takes several runs spread over hours.
- Moved items, with every artifact version, become readable to everyone who
  can read the repository.
