---
description: An admin copies the todo state of one or more projects from the computer
  they are on to the same projects' checkouts on other computers with one command
  that needs no running daemon, so another computer can continue the work.
---

# Todo State Transfer — Spec

## Required reads

- @docs/local/spec/domain/workflow.md

## What it is

The behavioral contract for `telec todo sync`: an admin, or an agent session
acting for one, copies the todo state of named projects from the computer the
command runs on (the origin) to the checkouts of the same projects on named
other computers (the targets). Each target's copy of a project's todo state is
replaced by the origin's, so the target can continue that work.

**Business value:** a person working across computers moves ongoing work to
another machine before closing the one it runs on, without hand-copying
databases or risking a torn copy of a live one. The command runs from a regular
terminal while the origin's daemon is stopped, which is the moment the admin
chooses to hand work over.

The transfer is a point-in-time copy in one direction. It does not pause work
on either computer, record which computer owns a project, or guard against both
computers working on the same project; the admin stops the origin's daemon
before transferring. Code does not move with it: a todo branch reaches the
target through the project's remote.

## Canonical fields

- **Reach:** admin only — an admin at a terminal, or a session an admin started
  without an agent role. A session carrying an agent role, or acting for the
  platform's principal, is refused
  (`local/projects/teleclaude/design/cli-authorization-matrix`).
- **Addressing:** a target is named by its computer name and reached as the
  user and host it announces in the cluster's peer registry, over key-based
  SSH. A target that is not online in the registry, or is the origin itself,
  is not transferred to.
- **Checkout resolution:** each target resolves its own checkout of a project
  from its own project registry. A target that has no checkout of the project
  is reported and skipped.
- **Transfer:** only the parts of the todo state that differ are sent, so a
  repeated transfer of a large todo state moves little data. Both computers'
  todo state may be in use while it runs. The transfer tool is provisioned on
  every computer by the installer
  (`local/projects/teleclaude/spec/feature/reconciliation/sqlite-sync-tool-provisioning`).
- **Verification:** after the copy, the target checks its copy's integrity and
  reports the result.
- **Outcome report:** one outcome per project and target — transferred,
  skipped with the reason, or failed with the cause. One pair's failure does
  not stop the others. The command exits unsuccessfully when any pair failed.

### Use cases

#### UC-TST1: A project's todo state reaches a target that has the project

```gherkin
Given an admin at a terminal on the origin computer
And a target computer that is online and has a checkout of the project
When the admin transfers the project's todo state to the target
Then the target's checkout holds the origin's todo state
And the target reports its copy intact
And the admin sees the pair reported as transferred
```

#### UC-TST2: The transfer needs no daemon on the origin

```gherkin
Given the origin computer's daemon is stopped
When the admin transfers a project's todo state to an online target
Then the transfer completes without the origin's daemon
```

#### UC-TST3: The target keeps running while it receives

```gherkin
Given the target computer's daemon is running and reading its todo state
When the admin transfers a project's todo state to that target
Then the transfer completes without stopping the target's daemon
And the target's daemon continues from the transferred todo state
```

#### UC-TST4: A repeated transfer sends only what changed

```gherkin
Given a project's todo state was transferred to a target before
And the origin's todo state has changed a little since
When the admin transfers it to that target again
Then the data sent is proportional to what changed, not to the size of the todo state
```

#### UC-TST5: A target without the project is skipped and the rest continue

```gherkin
Given the admin names two projects and a target that has a checkout of only one of them
When the admin transfers both projects' todo state to that target
Then the project the target lacks is reported as skipped, naming the missing checkout
And the other project's todo state is transferred
```

#### UC-TST6: An unreachable target fails alone

```gherkin
Given the admin names two targets and one of them is not online in the peer registry
When the admin transfers a project's todo state to both
Then the unreachable target's pair is reported as failed, naming why it could not be reached
And the online target receives the todo state
And the command exits unsuccessfully
```

#### UC-TST7: A copy that fails its integrity check is reported as failed

```gherkin
Given a transfer to a target completes but the target's copy is not intact
When the target checks its copy
Then the pair is reported as failed, naming the integrity check
And the command exits unsuccessfully
```

#### UC-TST8: A missing transfer tool is named with its remedy

```gherkin
Given the transfer tool is missing on the origin or on a target
When the admin transfers a project's todo state
Then each affected transfer is refused, naming the missing tool and the install step that provides it
And no target's todo state is changed by the refused transfer
```

#### UC-TST9: Only an admin can transfer todo state

```gherkin
Given a caller who is not an admin, or an agent session carrying an agent role, or a session acting for the platform's principal
When the caller asks to transfer a project's todo state
Then the command is refused before anything is sent
```

#### UC-TST10: An admin's own agent session can transfer todo state

```gherkin
Given an agent session an admin started without an agent role
When the agent transfers a project's todo state to an online target that has the project
Then the transfer is admitted and runs as it does for the admin at a terminal
```
