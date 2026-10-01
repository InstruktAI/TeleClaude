---
visibility: internal
number: 0106
date: 2026-10-01
description: Every home's local half is addressed by its own identity namespace — `local/<kind>/<slug>/…` — and by its own selector, so a published and a private snippet at the same relative path coexist and any reader tells from an identity alone whether it is published.
---

# A Home's Local Half Is Its Own Identity Namespace — ADR

## Context

Every documentation home has a published half and a local half. Identities were
derived as `<domain>/…` for a domain snippet, `projects/<slug>/…` for a
project's local snippet, and `people/<slug>/…` or `companies/<slug>/…` for a
person's or company's snippet in either half. A person or company home's
published half has no domain segment, so both of its halves derived the same
identity. The same relative path in both halves was therefore made a validation
error, and that error refused the home's whole publication.

A person needs exactly that shape: a published `principle/privacy` that tells
others what they share, and a local one that keeps for themselves what an agent
working for them should know. The error made that impossible, and the
collision was a property of the identity scheme, not of the content.

A tier selector (`--person`, `--company`, `--project`) also read both halves of
the named home at once, so a reader could not ask for just what a home publishes
or just what it keeps locally.

## Decision

- **A local snippet's identity carries the `local/` prefix**, for every home kind:
  `local/projects/<slug>/…`, `local/people/<slug>/…`, `local/companies/<slug>/…`.
  Published identities are unchanged. The one rule a reader learns is that an
  identity beginning with `local/` is indexed in place and never published, and
  any other identity is published.
- **The half-collision validation is retired.** The two halves of a home no
  longer share an identity, so the same relative path in both yields two
  snippets.
- **Selection addresses one half at a time.** A home selector reads the named
  home's published half; a new `--local` selector reads a home's local half — of
  the named home, or of the landed home when none is named. `--scope <kind>`
  remains a kind filter, adding nothing next to `--local`. The default read set
  is unchanged and still carries both halves of the caller's own homes.
- **Existing project-local identity references are renamed mechanically in every
  registered repository**, with no period in which both forms resolve.

## Consequences

- `local` joins the reserved identity prefixes; no published domain may carry
  that name.
- Every reference to a project-local identity in the old form becomes an
  unknown identity until it is rewritten. The documentation layout convergence
  rewrites it in every registered repository's tracked Markdown; non-Markdown
  literals are corrected with the code change.
- A tier selector no longer returns a home's local snippets; callers that want
  them pass `--local`. The default read set, through which help desks serve
  public local material, does not change.
- Stored todo artifacts and state that cite the old form are carried forward,
  as the earlier identity migration did.

## Alternatives Considered

- **Keep the validation error.** Rejected: it forbids the published-and-private
  pair the person home exists to hold.
- **One identity with two layers**, the local body appended for the owner when
  the published one is read. Rejected: it hides which material is private, and
  an agent must know to expect a second body under one name.
- **A `local` segment inside the home part** (`people/<slug>/local/…`). Rejected:
  it reads as a taxonomy position, differs from the project form, and leaves a
  rule with exceptions.
- **A bare `local/<taxonomy>/…` without the owner.** Rejected: a read set holds
  several homes' local halves at once, so the identity would mean different
  snippets in different sessions and lose its owner when copied.
