---
description: One reach rule, owned by identity, decides which platform data each principal
  may see — by the subject each record is about — and every surface that shows data
  to principals applies it on the receiving computer without a rule of its own.
visibility: internal
---

# Data Visibility — Spec

## What it is

Platform data shown to a principal is filtered by one rule: the principal's
**reach** over the **subject** each record is about. A subject is a registered
project, person, or company, or none for data about the platform itself; a
project subject also names its owner, as resolved where the record was made
(`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`).

Identity resolves each principal's reach once and publishes it. The rule lives
only there:

| Subject                             | Reached by                                                                      |
| ----------------------------------- | ------------------------------------------------------------------------------- |
| any, or none                        | a platform administrator, and the system principal                              |
| a company                           | every person on that company's roster                                           |
| a person                            | that person                                                                     |
| a project a company owns            | that company's administrators, and roster members assigned to it                |
| a project a person owns             | that person                                                                     |
| a project with no owner             | a platform administrator, and the system principal, only                        |
| the platform's shared documentation | a platform administrator, the system principal, and every company administrator |

A platform administrator and the system principal reach everything
unconditionally, including records with no subject and subjects the receiving
computer does not know. A platform role below administrator grants no reach of
its own. An agent session is judged by the principal at the root of its lineage
(`local/projects/teleclaude/spec/feature/identity/principal-resolution`).

Beside the subject, reach admits a principal's own records wherever they are:
conversations recorded under that principal, its own spawned chains included;
operations it started; and sessions its sessions spawned. Reading the outcome of
one's own act and following one's own workers do not depend on where that work
landed.

Every surface that lists or pushes platform data to a principal applies that
reach and holds no visibility rule of its own: session listings and live session
updates, conversation history, operation status, documentation depth,
notifications, project listings, and memory observations. Filtering happens on the computer that
shows the data, never on the computer that produced it. Records received from
another computer carry their subject and its owner, so a receiving computer that
does not know a project can still admit the owning company's people or the owning
person. Stored records carry their subject from the moment they are written;
records that existed before subjects were recorded receive theirs once.

Command clearance — whether a caller may run a command against a target — is a
separate, up-front decision (`local/projects/teleclaude/spec/feature/identity/command-clearance`)
and is not changed by this contract.

Three audience facts a record states about itself sit beside reach, and reach
neither widens nor narrows them. A documentation snippet its author published
`public` is readable by every caller; reach decides only which tiers a principal
reads in full (`local/projects/teleclaude/spec/feature/context/doc-selection-policy`). A
person's private local documentation is readable only by that person and the
<!-- planned-change:human-alerts-agent-only -->
system principal, platform administrators included (same contract). A
notification addressed to one person reaches only that person, through their own
channel, and appears on no shared surface, for platform reach too
(`local/projects/teleclaude/design/architecture/notification-delivery`); reach governs broadcast
notifications.
<!-- change:human-alerts-agent-only -->
system principal, platform administrators included (same contract). A
notification addressed to one person appears on no shared surface, for platform
reach too (`local/projects/teleclaude/design/architecture/notification-delivery`);
reach governs broadcast notifications.
<!-- /planned-change:human-alerts-agent-only -->

## Canonical fields

### Use cases

#### UC-DV1: A platform administrator and the system principal see everything

```gherkin
Given a person holding the platform administrator role, or an agent session whose lineage roots at the system principal
When it lists or receives platform data on any computer
Then every record is eligible, whatever its subject, except a notification addressed to another person
And a platform administrator who is not the system principal does not receive another person's private local documentation
And records with no subject are included
And records whose subject the showing computer does not know are included
```

#### UC-DV2: Everyone else sees exactly the subjects their reach admits

```gherkin
Given a person who is not a platform administrator
When the person, or an agent session rooted at them, lists or receives platform data
Then a record is shown only when their reach admits it: its subject is one they reach, or it is their own work
And no record outside that reach is shown, counted, or distinguishable from an absent one, apart from documentation its author published as public

Examples:
  | record's subject                        | shown to                                             |
  | a company                               | every person on that company's roster                |
  | a person                                | that person                                          |
  | a project owned by a company            | that company's administrators and assigned members   |
  | a project owned by a person             | that person                                          |
  | a project with no owner                 | nobody at this level                                 |
  | none                                    | nobody at this level                                 |
  | the platform's shared documentation     | every company administrator                          |
```

#### UC-DV3: A platform role below administrator reaches nothing by itself

```gherkin
Given a person whose platform role is member, contributor, or newcomer
And who holds no company membership and no project of their own
When the person lists sessions, history, projects, or notifications
Then only records about their own person home are shown
```

#### UC-DV4: Every data surface applies the same reach

```gherkin
Given two principals with different reach
When each views the same platform data through any surface that shows it
Then each sees exactly the records their reach admits, the same set on every surface
And documentation published as public and notifications addressed to one person follow their own audience instead

Examples:
  | surface                                                  |
  | the session listing, including closed and by-id listings |
  | live session updates in the TUI and web console          |
  | conversation history search and detail                   |
  | operation status                                         |
  | documentation, read in full only for reached tiers       |
  | notifications, both the initial list and live pushes     |
  | the project listing and the todos shown per project      |
  | memory observations: search, listing, and timeline       |
```

#### UC-DV5: A page is filled with visible records only

```gherkin
Given more records exist than one page holds, most of them outside the caller's reach
When a person without platform administrator reach requests a page of a listing
Then the page holds as many admitted records as exist up to the page size
And requesting the next page continues through admitted records only
```

#### UC-DV6: A record from another computer is admitted through the owner it carries

```gherkin
Given a record produced on another computer about a project this computer does not know
And the record names the project's owning company
When a roster member of that company who is assigned to the project, or one of its administrators, views it here
Then the record is shown
And a person with no relationship to that company does not see it
```

#### UC-DV7: A record whose subject cannot be resolved stays with platform reach

```gherkin
Given a record whose subject the showing computer cannot resolve to any reach, or whose subject is recorded as unknown
When a person who is not a platform administrator views that data
Then the record is not shown to them unless it is recorded under their own principal
And a platform administrator and the system principal still see it
```

#### UC-DV8: Reach follows the current configuration

```gherkin
Given a person was removed from a company roster, or unassigned from a project
When the configuration change has been applied on this computer
Then the next listing, and every live push after it, stops showing that person records they no longer reach
And a person newly added gains those records the same way
```

#### UC-DV9: Records written before subjects existed keep the right audience

```gherkin
Given sessions, conversation history, operations, and notifications that were stored before records carried a subject
When the platform has been upgraded
Then each such record is visible to the principals whose reach admits the subject it is derived to have
And a record whose subject cannot be derived is visible only to a platform administrator and the system principal
```

#### UC-DV10: Published documentation stays readable outside reach

```gherkin
Given a documentation tier the caller's reach does not admit
When an agent session reads documentation from that tier
Then it receives the snippets their author published as public
And it receives none of that tier's other snippets
```

<!-- planned-change:human-alerts-agent-only -->
#### UC-DV11: An addressed notification stays with its recipient

```gherkin
Given a notification addressed to one person
When any other principal, a platform administrator included, views the shared notification list or receives live notification pushes in the TUI or web console
Then that notification is not shown to them
And the addressed person receives it through their own channel
```
<!-- change:human-alerts-agent-only -->
#### UC-DV11: An addressed notification stays with its recipient

```gherkin
Given a notification addressed to one person
When any other principal, a platform administrator included, views the shared notification list or receives live notification pushes in the TUI or web console
Then that notification is not shown to them
```
<!-- /planned-change:human-alerts-agent-only -->

#### UC-DV12: A principal's own work stays visible outside its reach

```gherkin
Given a person whose reach does not include the project a record is about
And the record is a conversation recorded under that person, an operation they started, or a session one of their sessions spawned
When the person, or an agent session rooted at them, lists or reads that kind of record
Then the record is shown to them
And any other principal sees it exactly when their own reach admits it
```

#### UC-DV13: A company administrator reads the shared documentation in full

```gherkin
Given a person who administers a company and holds no platform role
When an agent session rooted at them reads the platform's shared documentation
Then every shared snippet is returned at full depth, internal ones included
And a member of that company below administrator receives only the shared snippets published as public
```

## Known caveats

- Access to data about the platform itself (no subject) stays with platform
  administrators and the system principal; a person below that needs a
  membership or a home to see anything.
- Acting on one named object — ending, messaging, or tailing a session — stays
  with command clearance and per-session access, which this contract does not
  change.
