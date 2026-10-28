---
visibility: public
number: 146
date: 2026-10-28
description: The GitHub workflow store keeps every artifact version as a version of a native GitHub issue artifact instead of an appended issue comment, requires the repository to serve issue artifacts, and reads no artifact content from comments.
---

# GitHub Store Keeps Artifact Versions as Native Issue Artifacts — ADR

## Context

The GitHub workflow store keeps each work item's artifact versions as
platform comments appended to the item's issue: one comment per version, split
across consecutive comments when large, with hidden machine data and a hidden
content marker in each. The issue body already shows the current input, so
every version of the input repeats text the issue already shows, and the
timeline people read is mostly artifact content. A version is written as
several requests, and verifying an item reads its whole comment history and the
edit history of each comment.

GitHub now offers issue artifacts: named Markdown, HTML or link documents
attached to an issue, each saving a version per update, with the account that
saved it recorded on the version.
They are a private preview, enabled per organization, that GitHub may change
without notice. The API serves only an artifact's 30 newest versions, takes no
conditional writes, and emits no webhook event and no timeline entry for a
change.

The items already on GitHub carry content comments. On the computer that
works a project, the working copy holds every version of every artifact
(ADR-0125, ADR-0142).

## Decision

- **Artifact versions are native artifact versions.** Each artifact of a work
  item is one issue artifact, and each version of it is one saved version of
  that artifact, written by the platform App. Workflow state that does not fit
  in the record is kept the same way. The record stays a comment and points at
  each artifact by its artifact number and the digest of the version it
  commits.
- **The preview is required.** A GitHub-backed project's repository must serve
  issue artifacts, as it must have the App installed; until it does, the
  project's workflow operations refuse with that cause. The store keeps no
  comment-based fallback.
- **Comments are not read for content.** No reader takes artifact content from
  a comment. Items whose records still point at content comments are brought
  to the native form by republishing their versions from the working copy of
  the computer that works the project, and the content comments that remain
  are removed afterwards.

## Consequences

- An issue's timeline carries the record, questions and lifecycle events; its
  artifacts sit beside the conversation, each with its own history, and a
  version is one request instead of one per comment part.
- A version is read and trusted through the version's own author, so the
  comment edit-history recovery is no longer needed for content.
- GitHub serves 30 versions per artifact. A rebuild from GitHub alone restores
  at most those; older versions remain only in the working copy that wrote
  them.
- A person's change to an artifact reaches the platform only when it next
  reads the item's artifacts, because GitHub announces none.
- If GitHub withdraws or changes the preview, the store stops writing and its
  artifact content on GitHub may become unreadable; a change of storage then
  needs its own decision.
- A computer running a store from before this decision reads the native form
  as missing content.

## Alternatives Considered

- **Keep content comments.** Rejected: it keeps the duplication and the
  multi-request writes, and GitHub now provides the versioned document the
  comments imitate.
- **Native artifacts with a comment fallback for repositories outside the
  preview.** Rejected: two write paths and two trust models for one record,
  kept indefinitely for a case no GitHub-backed project has.
- **Read both forms during a transition.** Rejected: a second reader of the
  record would stay in the store long after every item was converted, while
  the working copy already holds every version needed to republish an item.

## See Also

- docs/third-party/github-api/issue-artifacts.md — the API facts this decision rests on.
