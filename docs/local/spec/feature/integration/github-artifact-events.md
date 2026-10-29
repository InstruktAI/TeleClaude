---
description: Changes to the issue artifacts of a GitHub-backed project's open work items reach the cluster as github.issue_artifact events, through the same relay as webhook deliveries, found with conditional requests that download an issue's artifacts only when one of them changed.
delivered_by:
  - github-artifact-events
visibility: internal
---

# GitHub Artifact Events — Spec

## Required reads

- @docs/local/spec/feature/integration/github-webhook-normalization.md

## What it is

GitHub delivers a webhook for issues, comments, labels and relations, but none
for its issue artifacts. This
capability fills that one gap: a change to an artifact on the issue of a
GitHub-backed project's open work item reaches the cluster as a
`github.issue_artifact` event, published through the relay every GitHub
delivery takes, so a consumer reacts to it as it reacts to any GitHub event.
No other part of the platform reads artifacts to find out whether they changed.

**Business value:** the work on GitHub stays driven by events. People's
artifact edits can reach the work without each consumer polling GitHub, and
the platform spends almost no requests and almost no data on issues where
nothing changed.

## Canonical fields

- **Event.** One `github.issue_artifact` event per changed artifact, with the
  action `created`, `edited` or `deleted`, the issue number, the artifact's
  number, name and type, the account that saved its newest version and when
  it was saved. The event carries no artifact content; a consumer that needs
  the content reads that one artifact.
- **Relay.** The event is published as the project's `github.issue_artifact`
  platform event, with the origin and subject a webhook delivery for that
  project carries, through the claim that publishes a delivery once
  (`local/projects/teleclaude/spec/feature/integration/github-webhook-normalization`).
  The claim's identity is the issue, the artifact, the action and the time of
  the newest version the change concerns (for a deletion, the last version
  seen), so the same change is published once however many times it is found,
  and a deletion is never mistaken for the save before it.
- **Which issues.** The open issues of the project's repository work items.
  Closed issues, the ledger issue and the board issue are not looked at.
- **Where it runs.** On the project's active computer, the one computer that
  writes the project's claims; no other computer looks.
- **Data and requests.** Each look at an issue is one REST list request of its
  artifacts, sent with the entity tag of the previous answer. An issue whose
  artifacts are unchanged answers that nothing changed, with no body; an issue
  where any artifact changed answers with all of its artifacts, bodies
  included, once. Changes are found by
  comparing each artifact's number and the time of its newest version with
  what the previous answer held, never by hashing content. No GraphQL request
  is sent.
- **State.** For each open issue, the entity tag of the last answer and, per
  artifact, its number and the time and account of its newest version. The
  first look at an issue records that state and publishes nothing; changes are
  published from the next look on.
- **The platform's own saves.** A change whose newest version the platform's
  own App saved is published like any other, carrying that account, so a
  consumer tells a person's edit from the platform's write by the account.

## Known caveats

- GitHub announces no artifact change, so an event is published only when the
  issue is next looked at; the delay between an edit and its event depends on
  how often issues are looked at.
- An artifact edited more than once between two looks yields one event for its
  newest version.
- Issue artifacts are a GitHub preview; a repository that stops serving them
  publishes no artifact events.

## See Also

- docs/third-party/github-api/issue-artifacts.md — the artifacts API, its conditional reads and the events it does not emit.
