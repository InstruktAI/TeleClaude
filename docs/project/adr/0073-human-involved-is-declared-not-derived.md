---
visibility: internal
number: 0073
date: 2026-08-05
description: The Human-Involved commit footer is a per-commit declaration made by the committing agent, never derived from a todo's recorded human_involved fact.
---

# Human-Involved Is Declared, Not Derived — ADR

## Context

The sealed commit surface appends a `Human-Involved: <true|false>` footer to every
commit. An earlier design resolved that value mechanically wherever it could: inside
a todo's own slug worktree it read the todo's recorded `human_involved` fact from the
todos database, and only outside a worktree did it fall back to a flag the committing
agent passes. The appeal was that a recorded fact beats a declaration an agent might
get wrong.

Reading the integration path against the code showed the mechanical branch cannot
reach durable history. The commit that survives to `origin/main` is the integrator's
squash-merge delivery commit, made in the persistent integration worktree, which is
not any todo's slug worktree. The only two commits the derivation could stamp are the
pre-merge worktree sync, which `git merge --squash` discards along with the rest of
the branch, and the integrator's own worktree-cleanup commit, also made in the
integration worktree. The branch therefore ran a database read on every commit to
produce a value no reader of `origin/main` would ever see.

The two sources also disagree about what they mean. A todo's `human_involved` fact
records whether a human was present when that todo was _created_; the footer claims
whether a human was present for _this commit_. Deriving one from the other silently
projects an intake fact onto every commit in the todo's build.

## Decision

`Human-Involved` is a declaration made by the agent producing the commit, from its
own awareness of whether a human was present in that session. It is carried by the
`--human-involved` flag on `telec code commit` and defaults to `false` when no
declaration is made. The same shape applies uniformly at every commit call site: the
two internal ones — the pre-merge worktree sync and the integrator's worktree-cleanup
commit — declare nothing and so carry `false`.

The commit path reads no todo record and branches on no worktree location.
`Todo.human_involved` remains todo-level audit metadata and is never projected into
a commit message.

## Consequences

The value is honest about what it is: an assertion by the party in a position to
know, defaulting to the safe claim when nobody asserts. `false` never means "we
looked and found no human"; it means "nobody declared one," which is the same thing
for a reader deciding how much a commit was supervised.

The commit path loses a database dependency it never needed, and the sealed surface
keeps a single uniform contract across all three chokepoints rather than one that
changes shape by where the commit is made.

An agent that forgets the flag understates human involvement rather than overstating
it. That direction is deliberate: an invented claim of supervision is the failure
worth preventing.

## Alternatives Considered

**Keep the worktree-scoped derivation and accept that it only stamps discarded
commits.** Rejected: it is machinery whose output no durable record carries, and its
presence invites a future reader to trust a mechanically-sourced value that never
survives a delivery.

**Extend the derivation so the integrator's delivery commit reads the delivered
todo's fact.** Rejected: it would make every commit in a todo's delivery inherit an
intake-time fact about a different moment, which is a stronger misstatement than the
`false` default it would replace.
