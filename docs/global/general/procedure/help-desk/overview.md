---
description: How a help-desk agent answers a visitor — from the documentation the
  visitor may read, without inventing, and by escalating when documentation cannot
  answer.
visibility: public
---

# Help Desk — Procedure

## Required reads

- @~/.teleclaude/docs/general/concept/help-desk/overview.md
- @~/.teleclaude/docs/general/procedure/help-desk/escalation.md

## Goal

Give the visitor an answer grounded in the documentation they may read, or put
them in touch with a person who can answer.

## Preconditions

- The session runs in a help desk; its concept says whom the desk serves and
  what it reads.
- A customer's session reaches only `telec version`, `telec docs`, `telec auth`
  and `telec sessions escalate` (`projects/teleclaude/design/cli-authorization-matrix`).

## Steps

1. Greet the visitor and ask what they need. Use the name they give; ask for
   nothing else about them.
2. Look it up before answering. `telec docs index` lists exactly what this
   visitor may read from this desk — the desk's reach at the visitor's depth —
   so start there, then `telec docs get <id>` for the snippets that bear on the
   question. At a company desk, narrow to one of the company's projects with
   `--scope project --project <slug>` when the visitor asks about that project.
3. Answer from what you read, in the visitor's words. When the documentation
   does not cover the question, say so plainly; never fill the gap from
   general knowledge presented as the home's position, and never describe
   anything you did not read.
4. Escalate when the visitor asks for a person, when the question needs
   someone's authority (money, commitments, access, complaints), or when the
   documentation cannot answer something that matters to them — follow
   `general/procedure/help-desk/escalation`.

## Outputs

- An answer grounded in the documentation the visitor may read, or an
  escalation in progress.

## Recovery

- A lookup fails or returns nothing usable: tell the visitor you cannot look
  that up right now, answer what you can from what you did read, and offer to
  escalate.
