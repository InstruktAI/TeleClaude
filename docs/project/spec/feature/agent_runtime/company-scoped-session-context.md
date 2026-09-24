---
description: A session's company context — exposed to the agent from human membership, selected with an optional --company on creation and dispatch, carried forward, mapped from the source for event-started work, validated once at resolution, and published for tool subprocesses to read.
visibility: internal
delivered_by:
  - procedure-event-activation
---

# Company-Scoped Session Context — Spec

## What it is

Company context is the business scope a session operates under. It is a company
reference, never a location fact: the working directory, the source repository,
and the procedure's name do not select it.

Two origins establish it and are never conflated. Human-directed work carries
the person's established lineage together with the company they selected or
that follows unambiguously from their membership. Company automation started by
an event runs under the platform's system-principal contract, with the company
mapped from the configured event source; no human origin is fabricated for an
event.

Resolution happens once. A requested company is validated against the
requester's membership where the context is resolved, and what the session
publishes is already validated. Consumers read that answer rather than
re-deriving it.

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

#### UC-CSC1: A human-lineage session starts knowing its eligible companies

```gherkin
Given a person is a member of one or more companies
When a session carrying that person's lineage starts
Then the agent's startup context carries that person's resolved company memberships
And it carries any company already selected for the session
```

#### UC-CSC2: A company is selected explicitly on creation and dispatch

```gherkin
Given a person is a member of several companies
When a session is created or work is dispatched with an explicit company selection
Then the session operates under the selected company
And the selection supplies business context only
And it supplies no caller identity, role, or credential
```

#### UC-CSC3: Sole membership needs no explicit selection

```gherkin
Given a person is a member of exactly one company
When a session is created for that person with no explicit company selection
Then the session operates under that company
And no selection was required of the caller
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

- docs/project/spec/feature/agent_runtime/procedure-standing-agent.md — the company is one of the two facts identifying a procedure's continuing agent.
- docs/project/spec/feature/identity/session-identity-file.md — the incumbent per-session document read by CLI subprocesses.
