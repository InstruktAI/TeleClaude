---
visibility: internal
number: 0154
date: 2026-11-02
description: Each computer posts the conversation of the workflow sessions it ran to their GitHub work item on its own, best effort, with no fleet coordination; ordering across computers, a fleet-wide request share and recovery of a vanished computer's turns are given up for a mirror that needs no coordinating service.
---

# A work item's conversation is mirrored by each computer for its own sessions — ADR

## Context

On a project whose work record lives in the GitHub workflow store, the turns of
the sessions the workflow starts for an item are mirrored as comments on that
item's issue or pull request, so a visitor can follow the work on GitHub. The
sessions of one item can run on more than one computer over its life, and every
computer that posts shares GitHub's rate limits for the role Apps with the
pull request and review writes those Apps make.

A mirror that keeps every turn in completion order across computers, never
interleaves a turn's parts and holds the fleet to one share of GitHub's
content-creation limits needs one computer that posts for the fleet, custody of
other computers' turns on it, a relay between them and a durable fleet budget.
Each of these guarantees also meets cases no design can satisfy: a computer that
is gone still owes turns that nobody else holds, and GitHub's secondary limits
cannot be inspected.

The platform is moving to a local-first todo store with GitHub as an optional
sync and to a successor without a daemon, which cannot carry a coordinating
posting service.

## Decision

Each computer posts the turns of the workflow sessions it ran itself, each once
it is completed, through the store's existing GitHub requests, as the App mapped
to the session's role, after protection. It keeps per session the last turn it
posted, stops posting on a rate-limit response until the time GitHub names, and
mirrors only sessions created after the capability is live on that computer. No
computer posts another computer's turns, and nothing coordinates computers.

## Consequences

- A session's turns appear once and in completion order across restarts. Turns
  from different computers for one item, and a turn's parts after an
  interrupted post, can interleave; every comment carries its session, turn
  number and completion time so a reader can reconstruct the order.
- A computer that is gone for good takes its unposted turns with it.
- Each computer stops only on the refusals it receives; the fleet has no shared
  budget, so a busy period can delay the role Apps' pull request and review
  writes until GitHub allows requests again. The record's own App is never used.
- The mirror needs no master relay, no turn custody away from the computer that
  captured it and no fleet budget store, and fits a daemon-less successor that
  posts from where a session runs.
- With no fleet record of when mirroring began, each computer's own start bounds
  what it publishes; conversations held before it are never published.

## Alternatives Considered

- **One posting computer for the fleet.** Every computer hands its captured
  turns to the master, which keeps a fleet-wide share of the content-creation
  limits, holds the turns it is posting and completes them after a restart. It
  gives one budget and one stop, but needs a relay, master custody and a durable
  budget, and still cannot keep both order and progress when a computer that
  owes turns is gone. Rejected for the machinery it adds against what a reader
  gains.
- **Posting through a fleet-wide queue in the workflow store.** It keeps turns
  when a computer vanishes, but puts protected conversation content into the
  record's store and its sync, which a local-first store with optional GitHub
  sync does not carry. Rejected.
