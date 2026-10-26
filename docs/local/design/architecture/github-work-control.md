---
description: How each change a person makes to a GitHub-backed work item's issue reaches the workflow as the act it stands for, or is put back with its reason — once, in the issue's history order, on whichever computer serving the project handles it, whether GitHub delivered it or the platform caught up with it later.
delivered_by:
  - github-item-acts
visibility: internal
---

# GitHub Work Control — Design

## Purpose

Carry the behavior of
`local/projects/teleclaude/spec/feature/integration/github-work-control`:
turn a person's change to the fields the platform reflects on an item's issue
into the workflow act it stands for, and put back every change that does not
become an accepted act.

Each decision has one owner; this design owns only how they compose.

| Decision                                                                    | Owner                              | Contract                                                                                                                 |
| --------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Which GitHub field change stands for which act; whose changes count         | `integration`                      | `local/projects/teleclaude/spec/feature/integration/github-work-control`                                                 |
| Which person a GitHub login is                                              | `identity`                         | `local/projects/teleclaude/spec/feature/identity/human-identity-resolution`                                              |
| Whether an act is valid, and its effect                                     | `workflow`                         | `local/projects/teleclaude/spec/domain/workflow` and the feature specs of each act                                       |
| What the issue's fields should hold; reading, restoring and commenting them | `workflow` (GitHub adapter module) | `local/projects/teleclaude/design/architecture/workflow-store` (Issue history and field read, Field restore, Item title) |
| Receiving GitHub deliveries on every computer                               | `integration`                      | `local/projects/teleclaude/spec/feature/integration/github-webhook-normalization`, hook dispatch                         |
| Each change's disposition committed once, and its notice written once       | `workflow` (GitHub adapter module) | `local/projects/teleclaude/design/architecture/workflow-store` (History position, Put-back notices)                      |

The work-control handler is an integration edge: it translates a field change
into a typed workflow request, as the TUI translates a key press, and decides
nothing the workflow or the store decides.

## Inputs/Outputs

**Inputs**

- GitHub deliveries of the `issues` (title edited, labeled, unlabeled, closed,
  reopened, typed, untyped), `sub_issues` and `issue_dependencies` events,
  relayed to every computer and dispatched to the handler by a built-in hook
  contract beside comment routing's. A delivery names the issue; it only
  triggers handling of that issue and is never itself the change acted on.
- The catch-up sweep, run on every computer after each refresh of a
  GitHub-backed project it serves: the issues the platform App opened that
  GitHub reports updated since that computer's last sweep of the project.
- For one issue: the store's work item lookup; the issue's **history** after
  the item's history position — every change to a reflected field, in the
  order GitHub recorded it, each with its account, previous and new value;
  the issue's current fields beside their projected values; the repository
  permission of each acting account, read through the project's App; and the
  identity resolver's answer for each login.

**Outputs**

- For each change in the history, in order, one disposition committed with the
  item's next history position:
  - taken: the workflow request it stands for, through the same workflow
    service and validated update facade the TUI's routes call, with the
    person's principal as caller and GitHub as entry point;
  - put back: a put-back notice owed in the record, naming the change and the
    reason;
  - skipped: a change the platform's own App made.
- After the changes are disposed of, a restore of every reflected field whose
  current value still differs from its projected one, through the store.
- Structured logs at each disposition: taken, put back with reason, skipped as
  the platform's own write, no item.

## Invariants

- **Each change, in order.** Every change GitHub records to a reflected field
  of an item's issue receives exactly one disposition, in the order of the
  issue's history, whatever the order, number or absence of deliveries. A
  change superseded on GitHub before it is handled is still disposed of —
  taken, then followed by the later one, or put back with its notice.
- **One commit point per disposition.** The history position advances in the
  same conflict-checked record revision that commits the disposition: the act
  it leads to, or the owed notice, or nothing for a skipped change. Any
  computer serving the project may handle an issue; when two handle one
  change, the record's conflict check admits one, and the other refreshes and
  continues from the advanced position.
- **History, not current values, carries attribution.** A change is taken only
  when its own history entry names a person whose changes count at the time
  it is handled. A field that differs from its projection with no change in the
  history to account for it is restored, and its notice says no change by a
  person who may change the work was found.
- **A platform write never hides a person's change.** A reflection the App
  writes after a person's change — an owed write repaired by refresh on any
  computer — is a later history entry, skipped in its turn; the person's change
  before it is still disposed of, and the final restore writes the value the
  dispositions leave.
- **Designated fields only.** The issue number, the issue numbers of a
  sub-issue or blocked-by relation, labels, state and state reason, issue type
  and title value are the only inputs; no text is interpreted to choose an
  item or an act.
- **The workflow decides.** A refusal of the act is the workflow's own outcome
  and its reason, unchanged, is the notice's reason. A failure that is not a
  refusal — a write conflict, an unreachable store, a failed permission or
  history read — commits no disposition and leaves the change for the next
  handling.
- **One notice per put-back.** A notice is written from the record as a
  reflection, its envelope naming the history entry it answers; the writer
  recognizes a notice already on the issue for that entry, so a lost reply or
  an interrupted write never posts it twice.
- **Open act table.** The mapping from field change to act is one table the
  handler reads; a later delivery adds a row for another field or label
  without changing admission, history handling or put-back.

## Primary flows

### Handling one issue

```mermaid
sequenceDiagram
    participant T as Delivery or catch-up sweep
    participant H as Work-control handler (computer serving the project)
    participant S as GitHub adapter module
    participant ID as Identity resolver
    participant WF as Workflow service
    T->>H: issue of a project this computer serves
    H->>S: work item lookup (repository, issue number)
    alt no item
        H-->>H: nothing to do
    else item
        H->>S: history after the item's history position
        loop each change, in history order
            alt made by the platform's App
                H->>S: advance position (skipped)
            else counted person (configured, write access)
                H->>ID: resolve login
                H->>WF: act as that person, advancing the position
                alt refused
                    H->>S: owe notice with the workflow's reason, advancing the position
                end
            else anyone else, or no act for the change
                H->>S: owe notice with the reason, advancing the position
            end
        end
        H->>S: restore fields that still differ from their projection
        S->>S: write owed notices not yet on the issue
    end
```

A conflict at any advance refreshes the item and resumes from the position
the record now holds.

### Catch-up

After each refresh of a project it serves, a computer lists the platform App's
issues GitHub reports updated since its last sweep of that project and handles
each through the same flow. Its sweep mark is its own bookkeeping and only
saves work: the history position in the record decides what is still to be
handled, so a computer that sweeps late or twice disposes of nothing twice.

## Failure modes

- **No computer serving the project is running.** Nothing is handled
  meanwhile; the issue shows the person's change. The first handling after a
  serving computer starts disposes of every change since the item's history
  position.
- **A restore or notice write fails, or its reply is lost.** It is owed and
  written by the next refresh like any reflection; a notice already on the
  issue for its history entry is recognized and not written again.
- **A permission or history read fails.** No disposition is committed; the
  change waits for the next handling.
- **Several computers handle one issue at once.** Each advance is
  conflict-checked against the record's revision, so one disposition per
  change commits; the others refresh, and their GitHub reads are the only
  cost.
- **A history entry the module cannot read as a change of a reflected field.**
  It is skipped; if its field still differs afterwards, the final restore puts
  it back with the notice for an unaccounted change.
