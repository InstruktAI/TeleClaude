---
description: A configured owner or organization member approves a work item's spec on its GitHub issue, and a configured person's request for changes on its pull request sends the build back to fix with their review as the findings; every other approval or review changes nothing in the work and is answered where it was given.
delivered_by:
  - github-person-decisions
visibility: internal
---

# GitHub Approval and Review — Spec

## What it is

A person who follows a work item on GitHub
(`local/projects/teleclaude/spec/feature/workflow/github-work-record`) takes
two of their decisions on it there: approving the item's spec on its issue, and
requesting changes to its build on its pull request. Each is the same decision
they take in TeleClaude, taken as them and entering the workflow like any other
input; when the workflow accepts it stays the lifecycle's rule. Their other
changes to the issue are
`local/projects/teleclaude/spec/feature/integration/github-work-control`, and
their words reach the session working the item as their message
(`local/projects/teleclaude/spec/feature/integration/github-comment-routing`).

**Business value:** the person who reads a spec or a build on GitHub decides on
it where they read it, and the decision counts without anyone relaying it.

## Canonical fields

- **Who counts.** A configured person whose changes to an item count on GitHub
  (`local/projects/teleclaude/spec/feature/integration/github-work-control`)
  and who holds write access to the repository. Approving a spec is narrower:
  only such a person who owns the repository or is a member of the
  organization that owns it. An owner, member or collaborator without write
  access counts for neither decision.
- **Approving the spec.** The approval act on the item's issue
  (`local/projects/teleclaude/spec/feature/workflow/github-work-record`), by a
  person who may approve a spec, is their approval of the item's spec, as when
  they approve it in TeleClaude. The prepare lifecycle decides when an approval
  counts (`sdlc/procedure/lifecycle/prepare/overview`).
- **Requesting changes on the pull request.** A review that requests changes
  on the item's pull request, by a person who counts, is their build-review
  verdict when the work lifecycle accepts it
  (`sdlc/procedure/lifecycle/work/overview`). Their review, with its line
  comments, is that round's review report, attributed to them, and the build
  returns to fix.
- **Approving on the pull request.** Changes nothing in the work; the review
  reaches the session working the item as their message
  (`local/projects/teleclaude/spec/feature/integration/github-comment-routing`).
- **Answered, not taken.** An approval act or a review requesting changes that
  does not count changes nothing in the work: one by someone who may not take
  it, one at a moment the lifecycle does not accept it, and a review of a
  commit the build no longer stands on. The approval act is put back on the
  issue and the review is answered on the pull request, each with a comment
  saying why.
- **Which item and which build.** The item an act concerns follows only from
  the issue and pull request numbers GitHub reports, and the build a review
  concerns only from the commit GitHub reports it was given on. No title,
  description or comment text directs a decision to an item.

### Use cases

#### UC-GAR1: Approve a spec on GitHub

```gherkin
Scenario: An owner approves a spec that waits for approval
  Given a GitHub-backed project with an item whose reviewed spec waits for a person's approval
  And the repository's owner is a configured person with write access
  When the owner approves the spec on the item's issue
  Then the item's spec is approved by the owner

Scenario: A collaborator's approval does not count
  Given an item whose reviewed spec waits for a person's approval
  And a configured collaborator who neither owns the repository nor is a member of its organization
  When the collaborator approves the spec on the item's issue
  Then the item's spec is not approved
  And the issue carries a comment saying who may approve a spec
```

#### UC-GAR2: Send a build back from its pull request

```gherkin
Scenario: A collaborator requests changes on the current build
  Given a GitHub-backed project with an item whose build is under way on its pull request
  And a configured collaborator with write access to the repository
  When they request changes in a review of the commit the build stands on
  Then the build returns to fix with their review as its findings

Scenario: A review of an earlier commit is answered, not taken
  Given an item whose build has moved past the commit a configured collaborator with write access reviewed
  When they request changes in a review of that earlier commit
  Then the build carries on unchanged
  And the pull request carries a comment saying the review concerns an earlier commit

Scenario: A read-only collaborator's request for changes is answered, not taken
  Given an item whose build is under way on its pull request
  And a configured collaborator who holds only read access to the repository
  When they request changes in a review of the commit the build stands on
  Then the build carries on unchanged
  And the pull request carries a comment saying who may send a build back
```

## Known caveats

- Decisions reach the work only from repositories whose webhook delivers the
  issue and pull request review events they arrive in.
- A person sees their approval act on the issue until it is put back.
- An approval on the pull request is never a build-review verdict; the
  platform's own reviewer decides approval of a build.
