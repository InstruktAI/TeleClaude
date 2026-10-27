---
visibility: public
number: 138
date: 2026-10-27
description: A todo or bug filing returns a durable receipt once its request checks pass and completes after the response, in its project's acceptance order, so no filing makes its caller wait on the git lock or GitHub.
---

# A Filing Completes After Its Request Under a Receipt — ADR

## Context

A filing writes the todo entry, its first artifact and its state in one
working-copy transaction, after checking the work's pending documentation
against committed, reviewed revisions. That check holds the main-branch git
lock, which every commit and publication on the computer shares. On a
GitHub-backed project the same transaction also performs its GitHub round trips
while holding the working copy's write lock, a cost ADR-0125 accepted for every
write.

Filing answered inside its request, with a bounded wait for the git lock and a
refusal saying nothing was created when the bound ran out. Its total cost was
still the git wait plus every GitHub round trip of the write, and neither is
bounded by anything the caller controls. On 2026-10-26 a filing from an agent
returned "request timed out" while the todo had been created, other filings
failed with database-lock errors while unrelated writes held the working copy,
and the TUI froze until its own filing path was moved off its event loop. A
caller told that its filing timed out cannot know whether to file again.

ADR-0098 established the receipt contract for work that finishes after its
response, and ADR-0119 established that the command line never waits on a
receipt.

## Decision

A filing is receipt-backed work. Its request answers only the checks that need
neither the git lock nor a workflow-store write: slug, dependency and group
formats, content, schedule, plan and hold rules, a live todo holding the slug,
the creation lineage, and the involvement record resolved from the human's
presence at that moment. A request that passes returns an operation receipt.
The filing itself, from the documentation evidence check to the todo-created
event, runs after the response, and its outcome is delivered to the filing
session.

Filings of one project complete in the order their requests were accepted: a
filing starts once every earlier accepted filing of that project has ended.

## Consequences

- A filing request answers within its deadline whatever the git lock and
  GitHub cost, so a filing is never reported as a timeout and a reported
  refusal of the request always means nothing was filed.
- A caller cannot act on the new todo until its outcome arrives. A sequence of
  filings is still safe without waiting, because acceptance order holds within
  the project and an `--after` or `--group` reference to the previous filing
  finds it created.
- A refusal that only the filing can establish — missing or unreviewed
  documentation evidence, a parent that cannot become a holder, an unknown
  dependency — reaches the caller as a delivered outcome instead of the
  command's exit status.
- One slow filing delays the later filings of its project, and only those.
- A daemon restart settles accepted filings before it stops, as it does all
  accepted work. A filing interrupted by a crash ends stale, and its outcome
  says so; filing again is safe because a created todo refuses a second filing
  of its slug.
- The involvement record keeps its meaning, because it is resolved when the
  request is accepted rather than when the filing runs.
- Writes other than filing keep the cost ADR-0125 describes.

## Alternatives Considered

- **A longer wait inside the request.** Rejected: it fits slow work by
  stretching the caller's wait, and the caller's deadline still ends before the
  git lock and GitHub do in the cases that failed.
- **Push to GitHub after the local commit for every write.** Not taken here: it
  changes the commit point ADR-0125 chose for all writes, and a filing would
  still wait on the git lock for its documentation evidence check.
- **Receipt-backed filing without ordering.** Rejected: a todo filed with
  `--after` the todo filed just before it would be refused whenever the earlier
  filing had not yet completed.
