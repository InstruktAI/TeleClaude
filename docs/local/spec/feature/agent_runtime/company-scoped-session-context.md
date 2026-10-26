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
session carries no profile for it. A human-lineage session's startup context
lists the person's company memberships; this informs the agent but does not
select a company for the session.

Resolution happens once. A requested company resolves on the computer where
the session would run
(`local/projects/teleclaude/spec/feature/config/referent-resolution`) and is
validated against the requester's membership where the context is resolved;
what the session publishes is already validated. Consumers read that answer
rather than re-deriving it.

The company is recorded on the session record and nowhere else. A tool running
inside the session reads the context through the session it belongs to: its
session id names the record, and the context is resolved from that record when
the tool asks. The per-session identity document carries no company fact. When
required context is unresolved, the published answer distinguishes that state
from a resolved company and exposes no company value.

Company context is business scope alone. It changes neither caller identity nor
role, grants no site-administration standing, and confers no credential
privilege.

## Canonical fields

### Ubiquitous language

**Company context**
: The company a session operates the business of, together with the origin that established it.

**Eligible company**
: A company the requesting person is a member of, and therefore may operate under.

**Unresolved context**
: The state of a session whose company is required but absent or ambiguous — distinguishable by a reader from a resolved one.

### Use cases

#### UC-CSC2: A person chooses the company for work

```gherkin
Scenario: Use an explicitly selected company
  Given a person is a member of several companies
  When they create a session or dispatch work with an explicit company selection
  Then the work operates under the selected company
  And the selection supplies business context only

Scenario: Clarify an ambiguous company selection
  Given work requires company context and the person is a member of several companies
  And no company has been selected or established
  When the work is invoked
  Then the caller receives a correction naming eligible companies and how to select one
  And no company is guessed

Scenario: Refuse an ineligible company selection
  Given a person is not a member of the selected company
  When they create a session or dispatch work with that company
  Then the request is refused as ineligible
  And the refusal says the company is not among the person's eligible companies
  And no session operates under that company
```

#### UC-CSC4: An established company is carried forward

#### UC-CSC5: Ambiguity returns an actionable correction

#### UC-CSC6: Generic sessions need no company

```gherkin
Given work that requires no company context
When a session is created with no company selection
Then the session starts
And it operates without a company
And no company membership was required for it to exist
```

#### UC-CSC7: A requested company outside the requester's membership is refused

#### UC-CSC8: An event-started session carries the source's company under a system principal

#### UC-CSC9: A tool subprocess reads the resolved context

#### UC-CSC10: An unresolved context is distinguishable from a resolved one

#### UC-CSC11: A human-lineage session starts knowing its memberships

#### UC-CSC12: Sole membership resolves for tools without a profile

#### UC-CSC13: A company profile is present exactly when the session has a company

#### UC-CSC14: A company that does not exist is an error

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

- docs/local/spec/feature/agent_runtime/procedure-standing-agent.md — a company home is one of the homes a procedure's continuing agent answers; a session's company never identifies that agent.
- docs/local/spec/feature/identity/whoami-resolution.md — the surface through which a tool inside a session reads this context.
