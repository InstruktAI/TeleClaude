---
description: A configured owner or member files work by opening an issue on a GitHub-backed project, and a configured person refines a work item by editing its issue's description; the intake judges both as it judges a request in a session, and everything else on that path is answered or put back with a comment saying why.
delivered_by:
  - github-issue-intake
visibility: internal
---

# GitHub Work Filing — Spec

## What it is

A person who works on a GitHub-backed project files work by opening an issue,
and refines a work item by editing its issue's description. The issue's text
is raw input: the intake judges it the way it judges a request in a session
(`sdlc/policy/todo-creation-discipline`) — what kind of work it is, whether an
existing item already covers it, and what the item's input says — and writes
that input the way agents write it. The person's own words stay on the issue
as their comment. Everything else on this path that does not count is answered
or put back, with a comment saying why, so the issue never shows something the
work record does not hold.

**Business value:** the person running a project starts and corrects work
where they already are. Filing from GitHub gets the same judgment as filing in
a session, and the issue they opened is the one they keep following.

## Canonical fields

- **What arrives.** A GitHub delivery relayed for a project
  (`local/projects/teleclaude/spec/feature/integration/github-webhook-normalization`)
  that records an issue opened or reopened, or the description of a work
  item's issue edited. An issue one of the platform's own Apps opened is a
  record, never a filing.
- **Whose filings count.** An issue opened by a GitHub user — never a bot or
  App — whom GitHub reports as an owner or member of the repository and whose
  login resolves to a configured person
  (`local/projects/teleclaude/spec/feature/identity/human-identity-resolution`).
  An issue opened by an owner or member who is not a configured person is
  closed with a comment saying their issues are taken in once they are
  configured. Every other issue is left to the outsider gate, which hands an
  accepted one to the same intake.
- **Whose edits count.** A description edit by a GitHub user — never a bot or
  App — whom GitHub reports as an owner, member or collaborator of the
  repository and whose login resolves to a configured person.
- **Which item.** The item an edit concerns, and the item a reopened issue was
  closed against, are the GitHub store's answer for those issue numbers
  (`local/projects/teleclaude/design/architecture/workflow-store`, work item
  lookup). Text in a title, a description or a comment never decides which
  item an issue joins or duplicates; overlap is the intake's own judgment.
- **Filing.** The intake decides the item's kind among feature, change and bug
  — a bug needs a real occurrence, otherwise it is a change — its slug and its
  input. The issue the person opened becomes the item's issue: its
  description shows the item's projection and its input appears as its
  artifact comment
  (`local/projects/teleclaude/spec/feature/workflow/github-work-record`), and
  the person's original text stays as its own comment, attributed to them.
  When the kind differs from the issue type the person chose, the issue shows
  the decided kind and a comment says why. The item's creation record names
  the person as the authority it ran under and GitHub as its door
  (`local/projects/teleclaude/spec/feature/workflow/todo-creation`).
- **Not filed.** An issue whose work an existing item covers is closed as a
  duplicate linked to that item's issue. An issue that adds to an existing
  item not yet in build is carried into that item's input through its owner,
  and closed as a duplicate linked to it. An issue that is not work — a
  question, a discussion — is answered in a comment and closed as not planned.
  In none of these is an item created.
- **Reconsidering.** A configured owner or member who reopens an issue the
  intake closed as not work or as a duplicate has it taken in again.
- **Fields set while opening.** Labels and relations set on the issue when it
  was opened are treated, once its item exists, as the same changes on an
  item's issue are treated
  (`local/projects/teleclaude/spec/feature/integration/github-work-control`).
- **Refining.** A counted edit to the description of an active item's issue is
  a change to the item's input: the intake treats the edited text as raw input
  and revises the input the way agents write it, the description then shows
  the revised projection, and the edited text stays as its own comment,
  attributed to them. What the revised input does to work already prepared or
  building is the workflow's decision
  (`local/projects/teleclaude/spec/feature/workflow/drift-detection`).
  Successive edits leave the input reflecting the last edited text, with none
  lost and none applied out of order.
- **Put back.** An edit to the description by someone whose edits do not
  count, or of a delivered, removed or group-holder item, is put back: the
  description is restored to the item's projection and a comment says why —
  who may change the work from GitHub, or that the item takes no input changes
  in its state.
- **Once.** An opening or edit GitHub delivers more than once, or that several
  computers receive, is handled once.
- **Missed deliveries.** An opening or edit made while no computer received
  GitHub's deliveries is handled when the platform next brings the project up
  to date from GitHub, under the same rules.

### Use cases

#### UC-GWF1: File work by opening an issue

```gherkin
Scenario: A configured member's issue becomes a work item on that issue
  Given a GitHub-backed project
  And the person's configuration declares their GitHub account
  And they are a member of the repository
  When they open an issue describing new work
  Then the issue becomes a work item with the kind, slug and input the intake decided
  And the issue's description shows the item's input
  And their original text stays on the issue as their own comment

Scenario: The issue type is corrected to the kind the work really is
  Given a configured member opens an issue typed Bug that reports no real occurrence
  When the intake takes it in
  Then the work item is a change
  And the issue shows the Change type with a comment saying why

Scenario: An issue for work that already exists is closed as its duplicate
  Given a GitHub-backed project with a work item
  When a configured member opens an issue for the work that item already covers
  Then the issue is closed as a duplicate linked to that item's issue
  And no work item is created

Scenario: An issue that is not work is answered
  Given a GitHub-backed project
  When a configured member opens an issue asking a question
  Then the issue is answered in a comment and closed as not planned
  And no work item is created

Scenario: Reopening asks for reconsideration
  Given an issue the intake closed as not work
  When the configured member who can file reopens it
  Then the intake takes it in again
```

#### UC-GWF2: Refine a work item by editing its issue

```gherkin
Scenario: A configured person's edit revises the item's input
  Given a GitHub-backed project with a work item being prepared
  And a configured collaborator of the repository
  When they edit the item's issue description
  Then the item's input is revised from their edited text
  And the issue's description shows the revised input
  And their edited text stays on the issue as their own comment

Scenario: An edit by someone whose edits do not count is put back
  Given a public GitHub-backed project with a work item
  When someone who is not a configured owner, member or collaborator edits the item's issue description
  Then the description shows the item's input again
  And a comment on the issue says who may change the work from GitHub
  And the item's input is unchanged
```

## Known caveats

- Openings and edits reach the work promptly only from repositories whose
  webhook delivers issue events; otherwise they wait until the platform next
  brings the project up to date from GitHub.
- Between an opening or edit and its handling, the issue shows the person's
  text as they wrote it.
- A description edit on GitHub and an input change in a session at the same
  moment can lose one, as any two simultaneous changes to one item can
  (`local/projects/teleclaude/spec/feature/workflow/github-work-record`).
