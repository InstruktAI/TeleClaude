---
description: Inspect the retained workflow event occurrences of one item under the same item-read clearance and identity-owned data reach.
visibility: internal
delivered_by:
  - issue-128
---

# Item Event Occurrences — Spec

## What it is

The item occurrence view of `telec events` lets an operator follow what happened
to one workflow item. It reads occurrences of the item lifecycle's head-advanced,
claim-changed, waiting, ready and phase-advanced events, as their producing
contracts and the event catalog declare them. Type discovery remains owned by
`local/projects/teleclaude/spec/feature/event-catalog/event-discovery`.
Evidence and coverage follow `general/principle/grounding`; read authority
follows `sdlc/policy/security-awareness` and the identity-owned reach below.

## Canonical fields

### Selection and authority

The view selects the item's canonical subject in the registered project resolved
by ordinary item addressing. It reads events emitted on the reading computer;
the recorded emitting computer, project origin and item subject all match that
selection. Selection uses the recorded canonical item identity rather than an active-row
lookup; delivered or removed status leaves the retained trail addressable.

Command clearance is the ordinary item-read clearance. On each read, the
receiving computer applies identity's current reach to each occurrence's
recorded project origin and owner as its data-visibility subject, distinct from
the item reference used for selection, under
`local/projects/teleclaude/spec/feature/identity/data-visibility`.
Results, counts, continuation and coverage metadata follow that same visibility
boundary. This view defines no reader grant of its own.

### Retained window and output

The view reads a bounded retained window and supports bounded pages and opaque
continuation cursors. A reader can capture an observation cursor before an
operation and read a finite interval following it. The cursor scopes an
observation and grants no authority; every page is subject to the current
clearance and reach.

Occurrences appear in retained append order. Each carries its declared event
identity, type, time, source, subject and data under
`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`.
A logical occurrence occupies the append position of its first retained copy
in the read snapshot, including a copy before an observation cursor. The shown
envelope is that copy's envelope; later copies add no occurrence to any interval
or page. A cursor pins that logical ordering and the snapshot's retained
boundary. If retention loses evidence needed to preserve the ordering across
pages or an observation window, coverage is incomplete rather than moving a
later copy into that window. The view identifies the retained interval its
result covers and whether a continuation remains within that interval.

A successful empty result states that the covered retained interval contains no
matching visible occurrence. An unavailable event platform, an invalid or lost
cursor, and history pruned from a requested interval are reported explicitly,
with their cause and coverage limitation. They are distinct from an empty
covered result. Retained-only history is identified as such; an uncovered
interval establishes no absence of an emitted event.

### Use cases

#### UC-IEO1: Follow an item's workflow event trail

```gherkin
Given an operator's reach admits a project's workflow item
And that item has changed its claim and phase and published a work head
When the operator reads its retained item event trail
Then the view reports the matching visible occurrences in append order
And each occurrence identifies what happened and the item it concerns
And the operator can continue through the same finite retained interval
And the result states any limit on the history it establishes
And another project's or computer's same-named item contributes no occurrence
And data outside the operator's reach is neither shown nor counted
```

## Known caveats

- Observation and continuation handles live in the issuing daemon's bounded,
  shared cursor cache. A daemon restart or eviction of an older handle makes it
  invalid; an observation spanning that loss establishes no event absence.
- Events another computer emitted are outside this computer-local view.
- The view covers the five workflow occurrence kinds above and retained history,
  rather than other platform events or an item's complete lifetime.
- The recorded project and item subjects define the trail. Reusing an item
  subject shares that retained subject's history; the observation window,
  rather than the current adapter row address, selects the relevant interval.
