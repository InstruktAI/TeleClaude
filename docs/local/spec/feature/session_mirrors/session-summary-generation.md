---
description: 'Mirror writes generate no summary and call no language model. A summary stored by an earlier version stays stored and is never recomputed or cleared.'
visibility: 'public'
---

# Session Summary Generation — Spec

## Required reads

- @docs/local/spec/domain/session_mirrors.md

## What it is

Writing a mirror generates no summary. Mirror generation is transcript parsing
and store writes only; it makes no language-model call, so a mirror write has no
provider dependency, no per-write model cost, and no failure mode borrowed from a
summarizer.

No history surface reads a mirror summary: search renders a query-centered
snippet, and the detail view renders the conversation itself. A summary is
therefore not part of the mirror's contract. Summaries that an earlier version
stored remain on their mirrors as recorded; a later write of the same mirror
neither recomputes nor clears them.

## Canonical fields

### Use cases

#### UC-SSG-1: Writing a mirror calls no language model

#### UC-SSG-2: A stored summary is kept as recorded

## Known caveats

- A mirror first written after summaries stopped carries no summary. No
  surface depends on one.
