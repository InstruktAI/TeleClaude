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

```
Given the reconciliation loop or the event fanout writes a mirror
When the mirror is generated from its transcript
Then no language-model call is made
And the write completes without consulting any summarizer provider
```

#### UC-SSG-2: A stored summary is kept as recorded

```
Given a mirror that carries a summary stored by an earlier version
When the mirror is written again from its transcript
Then the stored summary is neither replaced nor cleared
```

## Known caveats

- A mirror first written after summaries stopped carries no summary. No
  surface depends on one.
