---
description: A project that selects the GitHub workflow store keeps its work items
  as issues in its own repository, where anyone can follow each item from intent to
  delivered commit without TeleClaude, and where only the platform App's own writes
  count as the record.
---

# GitHub Work Record — Spec

## Required reads

- @docs/local/spec/domain/workflow.md

## What it is

A project that declares the GitHub workflow store keeps its work items in its
own GitHub repository instead of the local todo database. The workflow runs
exactly as it does on the local backend: the same commands, phases, claims,
reviewers and stamps. What changes is where the record lives and who can read
it.

**Business value:** the people around a project follow its work where they
already are. Someone with access to the repository sees every work item, what
was intended, how it was prepared, reviewed and built, and which commit
delivered it, without running TeleClaude or asking an agent. The record no
longer lives on one computer.

How the store maps onto the repository is owned by
`local/projects/teleclaude/design/architecture/workflow-store`.

## Canonical fields

- **Selection:** a project selects the store, names its repository and names
  the platform App that writes the record in its declaration
  (`local/projects/teleclaude/spec/teleclaude-config`). The App must be
  installed on the repository with issue write access; until it is, every
  workflow operation on the project refuses with that cause and nothing falls
  back to a local store.
- **One issue per item:** each work item is an issue the platform App opened.
  Its title is the item's slug and its body is the item's current input.
- **Progress:** the issue carries the item's lifecycle phase as a label, and a
  claimed label while a session drives it. A platform-authored record comment
  states the item's phase, claimant, dependencies and delivery commit in
  readable form.
- **Artifacts:** every version of every artifact (input, plan, findings,
  review reports, log and the rest) is a platform-authored comment on the
  issue, appended in order and never rewritten. A version too large for one
  comment continues in the next.
- **Delivery and removal:** delivery closes the issue as completed, with the
  delivered commit in its record. Removal closes it as not planned;
  reactivation reopens it.
- **Project records:** commit reviews and documentation transfers, which
  belong to the project rather than one item, are appended to one
  platform-opened ledger issue.
- **Authority:** only what the platform App writes is the record. Labels,
  titles, bodies, comments and edits by anyone else are visible on GitHub but
  never change the workflow; a person steers the work through TeleClaude, not
  by editing the issue.

### Use cases

#### UC-GWR1: Follow a work item from intent to delivered commit

```gherkin
Scenario: A collaborator reads a delivered item on GitHub
  Given a project whose workflow store is GitHub
  And a work item was created, prepared, built, reviewed and delivered there
  When a collaborator with repository access opens the item's issue on GitHub
  Then they read the item's intent in the issue body
  And they read every artifact version in the order it was written
  And they see the phase changes as label events on the issue timeline
  And the closed issue names the commit that delivered the item

Scenario: An edit by someone else does not change the work
  Given a work item in progress on a GitHub-backed project
  When someone other than the platform App edits the issue body or changes its labels
  Then the workflow continues from the record the platform App wrote
```

## Known caveats

- Moving an existing local store's items to GitHub is not supported; a project
  that switches to the GitHub store starts from what its repository holds.
- Removing an item past its retention window does not delete the issue: the
  platform App cannot delete issues, so the issue and its history remain,
  closed and marked purged.
- Two computers changing the same item at the same moment can lose one
  change; work on one item from one computer at a time.
- Writes take GitHub round trips, so workflow commands on a GitHub-backed
  project are slower than on the local backend.
- A workflow command whose reply from GitHub is lost reports a failure even
  when GitHub applied the change; the change appears once the store next
  refreshes from GitHub.
