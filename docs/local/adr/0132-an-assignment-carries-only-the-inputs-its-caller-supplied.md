---
number: 132
date: 2026-10-25
description: A procedure assignment's inputs and its title are exactly what its caller supplied; declarations carry no default values and entry context never fills an absent argument.
---

# An Assignment Carries Only the Inputs Its Caller Supplied — ADR

## Context

A procedure declares the arguments it takes at launch. The declaration schema
let an optional argument carry a literal default, which the launch bound as
though the caller had supplied it and which continuation re-bound for a
session recorded before procedure entry. A survey of every procedure declaring
`parameters` — in the platform repository, its published documentation, the
people and company homes and the other workspace projects — found none that
declares a default, so the capability has no user; it exists to let a
declaration put a business value into an assignment nobody gave it.

The session title showed the role followed by a work subject chosen per entry
kind: a bound `branch` parameter for a direct invocation, the job name for a
scheduled run, the home for an activation. A scheduled job whose procedure
takes no arguments was therefore titled with its job name, which for a job
named after its role repeats the role in every title it produces. The rule
that chose the subject grew one case per entry kind and parameter name, and
each new entry kind or parameter would have added another.

## Decision

An assignment's inputs are exactly what its caller supplied. A declaration
gives an argument a name, a position and whether it is required, never a
value: a missing required argument refuses the launch, and an omitted optional
argument stays absent through binding, the persisted invocation and every
continuation. The procedure body decides what absence means.

The title follows the same rule: the role followed by the arguments the
assignment was supplied, or the role alone when it was supplied none. It is
one rule for every role, procedure and entry kind. Job name, home and
procedure ID are entry context; they keep their own records and are never a
title's subject.

## Consequences

- A declaration that still carries a default is refused at validation, so the
  capability cannot return silently through an authored procedure.
- A procedure that wants behavior when an optional argument is omitted states
  it in its body against the argument's absence.
- A scheduled run or an activation of a procedure that takes no arguments is
  titled with its role alone; telling runs apart is the job and home records'
  job, which session details already show.
- A title can lengthen when a procedure takes several arguments, because every
  supplied argument appears; the stored arguments and the title agree.

## Alternatives Considered

- **Keep optional defaults.** A procedure could keep a convenient value for an
  omitted argument, but the bound inputs would no longer tell what the caller
  asked for, and the title, the loader and continuation would each present a
  value nobody supplied.
- **Mark one parameter per procedure as the title subject.** Each procedure
  would choose its own subject, at the cost of a second declaration field and
  a validation rule, and a title that hides supplied arguments the marker does
  not name.
- **Keep entry context as the subject when no argument is supplied.** It
  distinguishes runs in a list, but it is the fallback that produced the
  duplicated title, and it needs a case for every entry kind.
