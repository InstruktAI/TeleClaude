---
visibility: internal
number: 0126
date: 2026-10-24
description: On a GitHub-backed project, tasks and creative-track items are kept in the GitHub store's working copy as that computer's own record and never published, instead of being published as issues or served from a second, local store beside the GitHub one.
---

# Non-Repository Work Stays in the GitHub Store Working Copy — ADR

## Context

A project on the GitHub workflow store publishes its work items as issues so
that people can follow its repository work on GitHub. Not every work item is
repository work. A task is an action the platform performs for a person, and
the creative track produces visual work rather than code; neither belongs in a
public repository's issue list, and the project's owner decided that they do
not appear there.

Those items still have to work on a GitHub-backed project. Once a project
selects GitHub, every workflow command reaches the GitHub store, and the local
store is frozen. The GitHub store serves the port through the local
implementation on a working copy (ADR-0125), whose guarantee so far was that
it holds nothing the repository lacks.

## Decision

The GitHub store keeps an item that is not repository work in its working copy
as that computer's own record, exactly as the local backend keeps it, and
publishes nothing of it. The push skips such an item; rebuild and refresh never
adopt a record of one. An item that becomes repository work is published in
full on its next change. An item that stops being repository work publishes
one last revision that records the change, and its issue is closed as not
planned.

## Consequences

- Tasks and creative-track items keep working unchanged on a GitHub-backed
  project, through the same port, commands and rules, with no second store and
  no routing by kind in any consumer.
- The working copy is no longer disposable as a whole: losing it loses that
  computer's non-repository work, as losing the local database loses the local
  backend's work. Repository work keeps its guarantee.
- Non-repository work is per computer, as on the local backend. Another
  computer neither sees nor rebuilds it.
- The rule deciding what is repository work has one owner, the GitHub store
  adapter, and is read from the item's own kind and state.

## Alternatives Considered

- **Publish tasks and creative-track items like other work.** Rejected: it puts
  work that is not about the repository into its public issue list, against the
  owner's decision.
- **Serve non-repository items from the local store beside the GitHub store.**
  Rejected: every port operation would route by item between two stores, lists
  would merge across them, and a change of kind would move an item between
  stores mid-transaction. It reintroduces the composition ADR-0125 avoided.
- **Leave non-repository items behind in the frozen local store.** Rejected:
  no workflow command reads that store after the switch, so the project's tasks
  and creative work would silently stop.
