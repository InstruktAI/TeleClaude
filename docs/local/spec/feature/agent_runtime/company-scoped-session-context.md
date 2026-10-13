---
description: A session's company context — set only by --company or by being started
  from a session that has one, carried to every worker, profiled only when set, never
  derived from location, validated once at resolution, and published for tool subprocesses
  to read.
visibility: internal
---

# Company-Scoped Session Context — Spec

## What it is

Company context is the business scope a session operates under. It is a company
reference, never a location fact: the working directory, the source repository,
and the procedure's name do not select it.

A session has a company only when it is created with one: through an explicit
selection, or by being started from a session that has one, which carries it to
every worker without restating. Only such a session carries a company profile.
Standing in a company's project gives a session no company and no profile: the
project says whose project it is, not whose business the session operates.

Two origins establish it and are never conflated. Human-directed work carries
the person's established lineage together with the company they selected.
Company automation started by an event runs under the platform's
system-principal contract, with the company mapped from the configured event
source; no human origin is fabricated for an event. A person with exactly one
eligible company needs no selection for a tool to resolve that company, but the
session carries no profile for it.

Resolution happens once. A requested company resolves on the computer where
the session would run
(`local/projects/teleclaude/spec/feature/config/referent-resolution`) and is
validated against the requester's membership where the context is resolved;
what the session publishes is already validated. Consumers read that answer
rather than re-deriving it.

The company is recorded on the session record and nowhere else. A tool running
inside the session reads the context through the session it belongs to: its
session id names the record, and the context is resolved from that record when
the tool asks. The per-session identity document carries no company fact.

Company context is business scope alone. It grants no site-administration
standing and confers no credential privilege.

## Canonical fields

### Ubiquitous language

**Company context**
: The company a session operates the business of, together with the origin that established it.

**Eligible company**
: A company the requesting person is a member of, and therefore may operate under.

**Unresolved context**
: The state of a session whose company is required but absent or ambiguous — distinguishable by a reader from a resolved one.

### Use cases

#### UC-CSC2: A company is selected explicitly on creation and dispatch

```gherkin
Given a person is a member of several companies
When a session is created or work is dispatched with an explicit company selection
Then the session operates under the selected company
And the selection supplies business context only
And it supplies no caller identity, role, or credential
```

#### UC-CSC4: An established company is carried forward

```gherkin
Given a session operates under an established company
When it dispatches a delegated session or subsequent work
Then that work operates under the same company
And the caller repeats no company selection to preserve it
```

#### UC-CSC5: Ambiguity returns an actionable correction

```gherkin
Given work requires a company context
And the requester is a member of several companies
And no company has been selected or established
When the work is invoked
Then the invocation returns a correction naming the eligible companies and how to select one
And no company is guessed
```

#### UC-CSC6: Generic sessions need no company

```gherkin
Given work that requires no company context
When a session is created with no company selection
Then the session starts
And it operates without a company
And no company membership was required for it to exist
```

#### UC-CSC7: A requested company outside the requester's membership is refused

```gherkin
Given a person is not a member of a company
When a session is created or work is dispatched selecting that company
Then the request is refused
And the refusal names that the company is not among the requester's eligible companies
And no session operates under it
```

#### UC-CSC8: An event-started session carries the source's company under a system principal

```gherkin
Given an event arrives from a configured source associated with a company
When a session is started to answer it
Then the session operates under that company
And it runs under the platform's system principal
And no human principal is presented as its origin
```

#### UC-CSC9: A tool subprocess reads the resolved context

```gherkin
Given a session with a resolved company context
When a tool running as a subprocess inside that session reads the session's published context
Then it reads the resolved company
And it reads the origin, distinguishing human-directed work and its human principal from system-principal company work
And it reads a context that is already validated against the requester's membership
```

#### UC-CSC10: An unresolved context is distinguishable from a resolved one

```gherkin
Given a session whose company context is absent or ambiguous
When a tool running as a subprocess inside that session reads the session's published context
Then it observes the unresolved state
And it can tell that state apart from a resolved company
And it does not observe a company value
```

#### UC-CSC11: A human-lineage session starts knowing its memberships

```gherkin
Given a person is a member of one or more companies
When a session carrying that person's lineage starts
Then the agent's startup context lists that person's company memberships
```

#### UC-CSC12: Sole membership resolves for tools without a profile

```gherkin
Given a person is a member of exactly one company
And a session carrying that person's lineage is created with no company selection
When a tool running inside the session reads the session's published context
Then it reads that one company as resolved
And the agent's startup context carries no company profile
```

#### UC-CSC13: A company profile is present exactly when the session has a company

```gherkin
Scenario Outline: The profile follows the session's company, never its location
  Given a session <how it was created>
  When it starts
  Then the agent's startup context <profile outcome>

  Examples:
    | how it was created                                              | profile outcome                   |
    | was created with a company selection                            | carries that company's profile    |
    | was started from a session that has a company                   | carries that company's profile    |
    | stands in a company's project and was created without a company | carries no company profile        |
```

#### UC-CSC14: A company that does not exist is an error

```gherkin
Given a company selection that does not resolve on the computer where the session would run
When a session is created or work is dispatched selecting it
Then no session is started
```

### Cross-context references

- **identity** — owns the person's company membership and the authorization
  decision behind it. This context requests resolution and publishes the
  validated answer; it never re-derives membership or grants standing the
  identity contract does not publish.
- **config** — owns the registered companies and the association between a
  configured event source and its company.
- **workflow** and other consumers — read the published context and neither
  restate nor re-validate it.

## Known caveats

- Company context and credential privilege are separate. A session carrying a
  company reference holds no administrative standing over that company's
  systems; operating credentials remain owned by the system being operated.
- The company-scoped knowledge surface is a separate capability owned by the
  documentation tier work; this context covers session scope only.

## See Also

- docs/local/spec/feature/agent_runtime/procedure-standing-agent.md — the company is one of the two facts identifying a procedure's continuing agent.
- docs/local/spec/feature/identity/whoami-resolution.md — the surface through which a tool inside a session reads this context.
