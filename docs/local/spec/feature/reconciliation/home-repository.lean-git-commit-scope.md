---
visibility: public
description: "The TeleClaude home keeps one local history of its durable material: the
  home's template-written .gitignore decides what enters it, and one recorder, the
  home snapshot, commits every admitted change periodically and on request."
---

# Home Repository — Spec

## Required reads

- @docs/local/spec/domain/reconciliation.md

## What it is

The TeleClaude home directory keeps one local history of the durable material
of every person and company the installation serves: their declarations,
masters, documentation and agent artifacts. The history keeps changes from
being lost and lets any earlier state be restored. It has no remote, so it does
not protect against losing the machine.

The home is a mixed tree. Beside that durable material sit secrets, runtime
databases, caches, generated output, projected editor settings and project
repositories. **The home's `.gitignore` decides what the history holds.**
Installation and commit-boundary maintenance write it from the platform's home
template, and it admits only the paths it names: everything else stays out of
the history, including material that appears in the home later. Git applies the
file as it applies any `.gitignore`; no second evaluation of the rule exists.

**One recorder writes the history: the home snapshot.** A snapshot records
every change the `.gitignore` admits — new, modified and removed material alike
— in one commit authored under the installation's own identity with a fixed
message, and records nothing when nothing changed. It runs at a fixed interval
and on request. A commit requested anywhere in the home through `telec repo
commit` runs a snapshot and reports its outcome. Nothing else commits in the
home: configuration writers and migrations leave what they write for the next
snapshot.

A snapshot passes the commit hooks the home has installed. When they refuse it,
nothing is recorded, the refusal names their findings, and the next snapshot
tries again. A snapshot that finds the home's `.gitignore` missing records only
changes to material the history already holds and warns that the file is
missing.

A snapshot is a commit on the home's main branch, so the home's commit-boundary
maintenance follows it as it follows any commit: documentation it records is
published by that maintenance.

## Canonical fields

### Use cases

#### UC-HOME-1: A person's or company's change to the home is kept

```
Given a configuration writer, a migration or a session changed durable material in the home
When the next snapshot runs
Then the change is in the home's history
And no one had to commit it
```

#### UC-HOME-2: Secrets and runtime state never enter the history

```
Given the home holds secrets, runtime databases, caches, generated output and project repositories beside its durable material
When a snapshot runs
Then only the paths the home's .gitignore admits are recorded
```

#### UC-HOME-3: The home has no remote

#### UC-HOME-4: A session asking to commit in the home gets a snapshot

```
Given a session in a person's or company's home finished a documentation change
When it requests a commit with telec repo commit
Then a snapshot records the change at once
And the home's maintenance publishes the documentation
```

#### UC-HOME-5: A missing .gitignore lets nothing new in

## Known caveats

- Backup and resilience beyond this machine are deliberately absent. A remote,
  replication or any recovery claim needs a design that settles encryption,
  exclusion of secrets, multi-device conflict, and who owns restoration.
- The `.gitignore` decides by path, not by the bytes of any version. A path it
  admits whose content later carries a credential reaches the history
  unexamined; per-version secret detection is not part of this contract.
- A path the `.gitignore` stops admitting stays in the history, and git keeps
  recording its changes until the path is removed from the index.
- Changes made between two snapshots are lost when the machine fails before the
  second one runs.

## See Also

- ~/.teleclaude/docs/general/design/configuration-tiers.md — the tier model this contract composes with.
