---
visibility: internal
number: 0156
date: 2026-11-03
description: TeleClaude's Blueprint is generated whenever a checkout's remote-tracking main advances, by a push from that checkout or a fetch, through the maintenance executor, rather than on every canonical-main commit, in CI, or synchronously before a push; an answer from a Blueprint behind the asker names the difference instead of reporting the Blueprint unavailable.
---

# TeleClaude's Blueprint follows remote main as each checkout observes it — ADR

## Context

The Blueprint is a gitignored cache at a checkout's root, read by that checkout
and by every slug worktree of it. Slug worktrees and the integration worktree
are created by fetching remote main and branching from it, so the revision a
prepared or built change starts from is remote main, not the canonical
checkout's local main.

Generation was canonical-main maintenance: every commit or merge on local main
extracted the whole tree. With many agents committing to TeleClaude's main this
ran about every ten minutes on one computer, each run taking a median 79 s and
up to 620 s, and the machine stalled. A measured run on the current tree takes
about 40 s from a cold cache and about 50 s with Graphify's per-file cache warm,
because building and clustering the whole graph dominates; a generation is never
cheap, so only how often it runs can change. A query also refused any Blueprint
whose revision differed from local main, so every answer after a commit waited
on a new extraction or reported the Blueprint unavailable.

Each computer holds its own canonical checkout and its own integrator, and each
pushes to remote main. The release pipeline also pushes a reconciliation commit
to remote main from CI, where no local hook runs.

Until 2026-10-10 the integrator regenerated the Blueprint after a delivery, from
remote main. That writer was retired together with a post-merge writer and a
query-triggered writer, so that one maintenance writer remained.

## Decision

TeleClaude binds its Blueprint maintenance to remote-main activation. A
committed update of the checkout's remote-tracking main, observed by a
reference-transaction hook after a push from that checkout or a fetch, records
a maintenance obligation and returns; the maintenance executor extracts the
remote main revision the checkout has observed when the action runs.
Canonical-main commits owe TeleClaude no Blueprint maintenance. Other
code-enabled projects keep canonical-main generation unless they declare the
same binding.

A query answers from the complete published generation even when its revision
differs from the asking checkout, and names that revision and the files in
which the asking checkout differs from it. The agent judges that difference.

## Consequences

- A computer extracts once per remote-main advance it observes, coalesced while
  an extraction runs, instead of once per local commit.
- A worktree started from remote main usually finds a Blueprint for its
  starting revision. While a newer one is being built it finds an older one
  together with the files that differ.
- Revisions pushed by another computer or by the release pipeline reach a
  computer's Blueprint when that computer next fetches, which slug-worktree and
  integration-worktree creation already do.
- A Blueprint failure leaves the previous generation answering and no longer
  holds a canonical-main activation unsettled.
- The single maintenance writer of the 2026-10-10 consolidation is preserved.

## Alternatives Considered

- **Build in CI and deliver to installations.** The graph is not part of the
  repository and is consumed from the checkout, so a CI build needs durable
  artifact storage, authenticated download, coverage of commits CI skips or
  cancels, and a delivery step for every checkout. Rejected as infrastructure
  for a cache.
- **Generate synchronously in the pre-push hook.** The pushed SHA is known
  there, but every push waits about a minute, a rejected push spends an
  extraction on a revision that never becomes remote main, and revisions pushed
  by another computer or by CI never reach this computer's Blueprint.
- **React to GitHub push webhooks through event-bound maintenance.** It would
  reach every computer at once, but delivery of push events to the platform is
  not established, and each computer would still have to fetch before
  extracting.
- **Keep canonical-main generation and make extraction incremental.** The warm
  per-file cache saves no time because whole-graph build dominates, and the
  graph would still describe local main rather than the revision worktrees
  start from.
- **Apply remote-main activation to every code-enabled project.** A project
  without a remote main workflow would lose automatic generation, which the
  change was not authorized to take away.
