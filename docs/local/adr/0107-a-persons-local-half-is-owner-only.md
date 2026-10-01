---
visibility: internal
number: 0107
date: 2026-10-01
description: A person's local documentation half is readable only by sessions carrying that person's identity and by the system principal; every other caller, administrators included, is refused with the door named, while company and project local halves keep visibility-based depth.
---

# A Person's Local Half Is Owner-Only — ADR

## Context

Read depth on a documentation tier followed one rule for every tier and both
halves: a caller with a relationship to the tier, or whose effective role for it
is `admin`, read it in full; everyone else read its `visibility: public`
snippets. The half a snippet lived in decided where it was served from, never
who could read it.

A person's local half is what that person keeps for themselves: privacy
choices, mail-handling preferences, standing instructions. Under the shared
rule a platform administrator read every person's local half in full, and an
outsider read any of it marked public. Administrator sessions run continuously
on platform work, so any of them could pull another person's private notes into
an unrelated agent's context, with only agent discretion keeping them out.

Company and project local halves are different: their help desks serve
outsiders the `visibility: public` part of exactly that material.

## Decision

- **Only that person and the system principal read a person's local half.** A
  session carrying the person's identity reads it in full, whatever the
  snippets' `visibility`; the system principal does too, for indexing and
  publication. Every other caller, platform and company administrators
  included, has no depth on it.
- **Naming it is refused, with the door named.** Naming another person's local
  half — by `--local --person <slug>` or by a `local/people/<slug>/…` identity —
  fails the command with a refusal stating that the owner's local documentation
  is private and that work on it happens in the owner's workspace. The refusal
  is the same whether or not that person is declared.
- **Arriving unnamed, it is left out.** When another person's local half would
  enter a default read set, because an invocation landed in that person's home,
  it is omitted without a refusal.
- **Only the person kind.** A person's published half keeps visibility-based
  depth, and company and project local halves keep their relationship and
  public-depth rule.

## Consequences

- The half now decides who may read in exactly one place, and the rule says so
  where the half/permission separation is stated.
- Administrators lose documentation access to people's private notes. Work on a
  person's own documentation happens in that person's workspace under their
  identity.
- The gate governs the documentation surface and the agents that use it, not
  the filesystem: an operator with disk access to a shared machine can still
  open the files.
- A refusal confirms nothing about which people are declared, preserving the
  rule that selectors disclose nothing.

## Alternatives Considered

- **Keep visibility-based depth for the person local half.** Rejected: it lets
  administrator reach and `public` markings expose material the person keeps
  for themselves.
- **Owner-only for every local half.** Rejected: help desks serve customers the
  public part of company and project local documentation, and a refusal there
  breaks them.
- **Withhold silently instead of refusing.** Rejected for named reads: a
  refusal that names the door tells the caller where the work belongs, instead
  of an empty answer that looks like missing documentation.
