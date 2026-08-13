---
description: 'Mirror listing is retired as a distinct surface. Enumerating stored conversations for one identity is served by history search; enumerating live and closed sessions is served by the sessions surface.'
visibility: 'public'
---

# Historical Mirror Listing — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

There is no mirror-listing verb on the history surface. Enumerating stored
conversations without a search term is not a capability the history surface
offers: a chronological page of mirrors carries no discriminator, and the
summary blurb that would differentiate its rows is not reliably distinct
between sessions.

The two questions the listing verb was reached for are each answered
elsewhere. _Which conversations belong to this person_ is a filter on history
search, which applies it alongside the full-text match and the role band.
_Which sessions exist, running or finished_ is a question about sessions
rather than about the archive, and the sessions surface answers it.

The store-level listing capability that backed the verb is retired with it;
nothing else calls it.

## Canonical fields

### Use cases

#### UC-HML-1: No listing verb exists on the history surface

```
Given an operator invokes a mirror-listing verb on the history surface
Then no such command is offered
And the surface's help does not advertise one
```

#### UC-HML-2: Identity enumeration is a search filter

```
Given an operator wants the stored conversations belonging to one identity
When they filter history search by that identity
Then the matching mirrors are returned, including mirrors whose session record no longer exists
And the caller's role band applies before any row is returned
```

## Known caveats

- Mirrors whose session record has been pruned are reachable through search
  but carry no TeleClaude id to enumerate them by; search states the namespace
  of whatever identifier it prints.
