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
  is not transferred to. An offline target is reported as failed, naming why it
  could not be reached.
- **Checkout resolution:** each target resolves its own checkout of a project
  from its own project registry. A target that has no checkout of the project
  is reported and skipped; other project-target pairs continue.

<!-- planned:github-store-adapter -->

- **GitHub-backed projects:** a project whose workflow store is GitHub has no
  todo state to copy, because every computer reads it from the project's
  repository (`local/projects/teleclaude/spec/feature/workflow/github-work-record`).
  It is reported and skipped; other projects continue.

<!-- /planned:github-store-adapter -->

- **Transfer:** only the parts of the todo state that differ are sent, so a
  repeated transfer of a large todo state moves little data. Both computers'
  todo state may be in use while it runs. A target daemon may remain running
  and continues from the transferred state. The transfer tool is provisioned
  on every computer by the installer; if it is absent on either side, the
  affected pair is refused with the install remedy before target state changes.
- **Verification:** after the copy, the target checks its copy's integrity and
  reports the result; a failed check marks that pair failed.
- **Outcome report:** one outcome per project and target — transferred,
  skipped with the reason, or failed with the cause. One pair's failure does
  not stop the others. The command exits unsuccessfully when any pair failed.

### Use cases

#### UC-TST1: Move a project's todo work to another computer

```gherkin
Given an admin at a terminal on the origin computer
And a target computer that is online and has a checkout of the project
When the admin transfers the project's todo state to the target
Then the target's checkout holds the origin's todo state
And the target reports its copy intact
And the admin sees the pair reported as transferred
```

#### UC-TST2: The transfer needs no daemon on the origin

#### UC-TST3: The target keeps running while it receives

#### UC-TST4: A repeated transfer sends only what changed

#### UC-TST5: A target without the project is skipped and the rest continue

#### UC-TST6: An unreachable target fails alone

#### UC-TST7: A copy that fails its integrity check is reported as failed

#### UC-TST8: A missing transfer tool is named with its remedy

#### UC-TST9: Only an admin can transfer todo state

#### UC-TST10: An admin's own agent session can transfer todo state
