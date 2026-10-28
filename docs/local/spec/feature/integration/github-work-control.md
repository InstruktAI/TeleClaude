---
description: A configured person changes a GitHub-backed work item from its issue — title, icebox, hold, removal, kind, group and dependencies — and each change becomes the matching workflow act taken as them; every change that does not become an accepted act is put back with a comment saying why.
delivered_by:
  - github-item-acts
visibility: internal
---

# GitHub Work Control — Spec

## What it is

A person who works on a GitHub-backed project's work on GitHub changes a work
item from its issue the way they change it in the TUI or CLI. A change they
make to a field the platform reflects on the issue
(`local/projects/teleclaude/spec/feature/workflow/github-work-record`) becomes
the workflow act that field stands for, taken through the workflow as that
person. Whether the act is valid is the workflow's decision
(`local/projects/teleclaude/spec/domain/workflow`). A change that does not
become an accepted act is put back, with a comment saying why, so the issue
never shows something the work record does not hold.

**Business value:** the person running a project works on both ends. What
they do to an item on GitHub counts, with no agent watching GitHub for them
and no second visit to the TUI, and what GitHub shows stays the truth about
the work.

## Canonical fields

- **What arrives.** A GitHub delivery relayed for a project
  (`local/projects/teleclaude/spec/feature/integration/github-webhook-normalization`)
  that records a change to the issue of a repository work item: its title
  edited, a label added or removed, the issue closed or reopened, its issue
  type set or removed, a sub-issue added or removed, or a blocked-by relation
  added or removed. A change written by one of the platform's own Apps is the
  platform's reflection and is no act.
- **Which item.** The item a change concerns, and the item at the other end of
  a sub-issue or blocked-by relation, are the GitHub store's answer for those
  issue numbers
  (`local/projects/teleclaude/design/architecture/workflow-store`, work item
  lookup). Nothing is read from a title, a description or a comment to decide
  which item a change concerns.
- **Whose changes count.** Only a GitHub user — never a bot or App — who
  holds write access to the repository and whose login resolves to a
  configured person
  (`local/projects/teleclaude/spec/feature/identity/human-identity-resolution`).
  Being an owner, member or collaborator without write access is not enough,
  and neither is being the issue's author. The act is taken as that person,
  as when they act in the TUI.
- **The acts.**

| On the item's issue                                 | Act                                                              |
| --------------------------------------------------- | ---------------------------------------------------------------- |
| Title changed                                       | the item's title becomes the new title; its slug does not change |
| `status:icebox` added / removed                     | freeze / unfreeze                                                |
| `status:on-hold` added / removed                    | hold, recorded as set on GitHub by that person / release         |
| Closed as not planned / reopened                    | remove / reactivate                                              |
| Issue type set to Feature, Change or Bug            | change the item's kind                                           |
| Another item's issue added / removed as a sub-issue | that item moves into / out of this item's group                  |
| Blocked by another item's issue added / removed     | a dependency on that item is added / removed                     |

- **The item's title.** A title a person gave the issue is the item's title
  and stays on the issue until a person changes it again; an item no person
  has retitled carries the title the work record derives from its input.
- **Put back.** Every other change to a field in the table above is put back:
  a change by someone whose changes do not count, a change that stands for no
  act (a `stage:` label, a close as completed or as a duplicate, a type that
  names no kind), a relation to an issue that is no item of the project, and
  an act the workflow refuses. The platform restores the field to what the
  work record holds and comments on the issue, naming the change and why it
  did not count: who may change the work from GitHub, that the change stands
  for no act, or the workflow's own refusal.
- **Outside this contract.** Labels that are not the platform's, assignees,
  milestones and an issue that belongs to no item are left as they are. The
  issue's body and the item's pull request stay under the work record's
  authority.
- **In order.** Changes to one issue are taken in the order they were made. A
  change the item already holds, such as GitHub delivering the same change
  again, is no act: the item is unchanged and nothing is put back.
- **Which computer acts.** A change to an item a session holds is handled on
  that session's computer; a change to any other item is handled on the
  project's active computer, the one computer the project names for its work
  (`local/projects/teleclaude/spec/feature/workflow/driver-admission`). Every
  other computer ignores it.

### Use cases

#### UC-GWC1: Change a work item from its GitHub issue

```gherkin
Scenario Outline: A configured person's change becomes the workflow act
  Given a GitHub-backed project with a work item
  And the person's configuration declares their GitHub account
  And they hold write access to the repository
  When they <change> on the item's issue
  Then the item <outcome> in the workflow, as when they do it in the TUI
  And the issue keeps their change

  Examples:
    | change                                   | outcome                          |
    | rename the issue                         | carries the new title            |
    | add the icebox label                     | is in the icebox                 |
    | add the on-hold label                    | is held                          |
    | close the issue as not planned           | is removed                       |
    | change the issue type to Bug             | is a bug                         |
    | add another item's issue as a sub-issue  | holds that item in its group     |
    | mark the issue blocked by another item's issue | depends on that item       |

Scenario: A change the workflow refuses is put back with its reason
  Given a GitHub-backed project with a work item whose build has started
  And a configured person with write access to the repository
  When they change the issue type on the item's issue
  Then the issue type is back to the item's kind
  And a comment on the issue says the workflow refused the change and why
```

#### UC-GWC2: GitHub shows only what the work holds

```gherkin
Scenario Outline: A change by someone whose changes do not count is put back
  Given a public GitHub-backed project with a work item
  When <someone> closes the item's issue
  Then the issue is open again
  And a comment on the issue says who may change the work from GitHub
  And the item is unchanged in the workflow

  Examples:
    | someone                                                   |
    | a GitHub user who is not a configured person               |
    | a configured member of the repository without write access |
    | the outside author of the issue the item was accepted from |

Scenario: A change that stands for no workflow act is put back
  Given a GitHub-backed project with a work item being prepared
  When a configured person with write access adds a stage label to the item's issue by hand
  Then the label is removed again
  And a comment on the issue says the change stands for no act
```

## Known caveats

- Changes reach the work only from repositories whose webhook delivers issue,
  sub-issue and issue-dependency events.
- Between a change and its handling the issue shows the person's change.
- A change GitHub does not deliver, or that arrives while the computer that
  should handle it is not running, is neither taken nor put back: the issue
  shows it although the work does not hold it, until the platform next writes
  that field from the work. Nothing reads the issue's history to catch up on
  missed changes.
