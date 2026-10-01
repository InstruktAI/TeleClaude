---
visibility: internal
number: 0104
date: 2026-09-29
description: A todo's kind is supplied by whoever files it and is required at creation; there is no kindless intake and no autonomous classification step.
---

# Every Todo Is Created With Its Kind — ADR

## Context

ADR-0015 made kind optional at intake. A todo filed without a kind was stored
with no kind and no lifecycle phase, and an autonomous classifier session was
dispatched to read the input and assign a kind afterwards. The TUI's new-todo
action adopted that path and created every todo without a kind.

The classification path carried its own dispatch lane, session command,
session role, assignment stamp and "awaiting classification" representation,
and every consumer of todo state had to account for a todo with no kind. That
extra surface failed in practice: the classifier could not launch for months
because its command had no session role, so TUI-created todos never entered a
lane. The state it introduced also leaked. A display label for the
unclassified state was published in the canonical lifecycle-phase field and
fed back into readiness decisions.

The person filing a todo already knows whether it is a feature, a change, a
bug or a task. Classification recovered, at the cost of an agent session, a
fact the filer held at the moment of filing.

## Decision

Kind is required at creation on every creation surface. The filer chooses one
of `feature`, `change`, `bug` or `task`, and the kind maps one-to-one onto the
todo's lifecycle lane from the moment the todo exists. There is no kindless
todo and no autonomous classification step. A wrong kind is corrected through
the ordinary todo update.

This supersedes the part of ADR-0015 that made kind optional at intake and
classification autonomous. ADR-0015's kind vocabulary and entry-point model
stand.

## Consequences

- Every todo has a lane from creation, so no dispatch path, session role,
  stamp or state representation exists for an unclassified todo, and consumers
  of todo state never branch on a missing kind.
- Filing costs one explicit choice. A raw brain dump can no longer be filed
  without deciding what it is; the filer picks the closest kind and corrects it
  later if needed.
- No agent interprets unframed intent to pick a lane, so a misfiled kind
  surfaces in the lane it entered rather than being caught by a classifier.
- The kindless parking hold that ADR-0053 kept "before classification" has no
  subject left.

## Alternatives Considered

- **Keep classification and repair its dispatch.** Rejected: it keeps a lane,
  a role, a stamp and a pseudo-state alive to recover a fact the filer already
  holds, and each of those surfaces has already failed or leaked once.
- **Default a missing kind to one value.** Rejected: a default silently routes
  work into a lane nobody chose, which is worse than refusing the creation.
