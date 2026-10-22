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

An unresolved or unknown subject is not treated as none or as public. It is
visible only to a platform administrator or the system principal, unless it is
the principal's own record. Listings filter by reach before pagination, so
each page contains only admitted records and the next page continues through
that same filtered set.

Beside the subject, reach admits a principal's own records wherever they are:
conversations recorded under that principal, its own spawned chains included;
operations it started; and sessions its sessions spawned. Reading the outcome of
one's own act and following one's own workers do not depend on where that work
landed.

Every surface that lists or pushes platform data to a principal applies that
reach and holds no visibility rule of its own: session listings and live session
updates, conversation history, operation status, documentation depth,
project listings, memory observations, and the messages that tell a person about
a published domain's events. Filtering happens on the computer that shows or
sends the data, never on a computer that only produced it elsewhere. Records
received from another computer carry their subject and its owner, so a receiving
computer that does not know a project can still admit the owning company's
people or the owning person. Stored records carry their subject from the moment
they are written; records that existed before subjects were recorded receive
theirs once. Their audience follows that derived subject; when no subject can
be derived, only platform administrators and the system principal see the
record.

Command clearance — whether a caller may run a command against a target — is a
separate, up-front decision (`local/projects/teleclaude/spec/feature/identity/command-clearance`)
and is not changed by this contract.

Two audience facts a record states about itself sit beside reach, and reach
neither widens nor narrows them. A documentation snippet its author published
`public` is readable by every caller; reach decides only which tiers a principal
reads in full (`local/projects/teleclaude/spec/feature/context/doc-selection-policy`). A
person's private local documentation is readable only by that person and the
system principal, platform administrators included (same contract).

A third fact beside reach concerns presentation, not readability: a session
recording that no person watches it, an unattended procedure agent, is left out
of a principal's default view of sessions — the session listing that asks for
neither every session nor ids, and live session updates — while reach
still decides whether a listing that asks for it shows it
(`local/projects/teleclaude/spec/domain/agent_runtime`).

## Canonical fields

### Use cases

#### UC-DV1: A platform administrator and the system principal see everything

```gherkin
Given a person holding the platform administrator role, or an agent session whose lineage roots at the system principal
When it lists or receives platform data on any computer
Then every record is eligible, whatever its subject
And a platform administrator who is not the system principal does not receive another person's private local documentation
And records with no subject are included
And records whose subject the showing computer does not know are included
```

#### UC-DV2: Everyone else sees exactly the subjects their reach admits

```gherkin
Given a person who is not a platform administrator
When the person, or an agent session rooted at them, lists or receives platform data
Then a record is shown only when their reach admits it: its subject is one they reach, or it is their own work
And no record outside that reach is shown or counted
And no record outside that reach is distinguishable from an absent one, apart from documentation its author published as public and a session the caller names by its id to inspect, which is refused as outside the caller's reach (`local/projects/teleclaude/spec/feature/agent_runtime/session-inspection`)

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

#### UC-DV4: Every data surface applies the same reach

```gherkin
Given two principals with different reach
When each views the same platform data through any surface that shows it
Then each sees exactly the records their reach admits, the same set on every surface
And documentation published as public follows its own audience instead
And an unattended procedure agent's session is left out of the default session listing and live session updates

Examples:
  | surface                                                  |
  | the session listing, including closed and by-id listings |
  | live session updates in the TUI and web console          |
  | conversation history search and detail                   |
  | operation status                                         |
  | documentation, read in full only for reached tiers       |
  | the project listing and the todos shown per project      |
  | memory observations: search, listing, and timeline       |
  | messages telling a person about a published domain event |
```

#### UC-DV5: A page is filled with visible records only

#### UC-DV6: A record from another computer is admitted through the owner it carries

#### UC-DV7: A record whose subject cannot be resolved stays with platform reach

#### UC-DV8: An operator's access changes take effect with the new reach

```gherkin
Given an operator changes a person's company membership or project assignment
When the change is applied on a computer that serves the affected records
Then a person removed from the relationship no longer sees records it admits
And a person added to the relationship sees records their new reach admits
And these outcomes take effect on the next listing or live push after the change is applied
```

#### UC-DV9: Records written before subjects existed keep the right audience

#### UC-DV10: Published documentation stays readable outside reach

#### UC-DV11: An addressed notification stays with its recipient

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

#### UC-DV14: An unregistered desk visitor reaches what was recorded under their own platform identity

```gherkin
Given a help-desk visitor the platform does not know as a registered person
And memories were recorded from that visitor's conversations under the platform identity they write from
When an agent session serving that visitor at a desk receives memories
Then the memories recorded under that platform identity are admitted to that session
And no memory recorded under any other identity is admitted to it
And no record is admitted to it for being about the desk's home
And the people whose reach admits the desk's home see those same memories, as records about that home
```

## Known caveats

- Access to data about the platform itself (no subject) stays with platform
  administrators and the system principal; a person below that needs a
  membership or a home to see anything.
- Acting on one named object — ending, messaging, or tailing a session — stays
  with command clearance and per-session access, which this contract does not
  change.
- On the computer that holds it, a session record that carries a human email
  but no stored principal is not admitted as that person's own record by the
  session listing, the session record read, or conversation history attributed
  to that session. Those reads match the stored principal, not the principal
  the email resolves to
  (`local/projects/teleclaude/spec/feature/identity/principal-resolution`), so
  the person reaches such a session and its attributed history only through
  subject reach; platform administrators and the system principal reach it as
  they reach everything. A session another computer shares is judged by the
  principal resolved for it.
