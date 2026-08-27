---
description: Run a person's calendar on their behalf — brief them on what is ahead, and schedule, move, cancel, or answer invitations under mandate.
activation_trigger: Use when the person asks what is coming up, asks about their availability, asks to book, move, cancel, or answer something in their calendar, or when a scheduled run of their assistant covers their calendar.
---

# Calendar Management — Procedure

## Required reads

@~/.teleclaude/docs/personal/policy/assistant-conduct.md
@~/.teleclaude/docs/personal/spec/person-knowledge.md
@~/.teleclaude/docs/personal/spec/tools/gog-cli.md

## Goal

Keep the person's calendar in the shape they want it: tell them what is ahead,
and make the changes they have authorized.

## Preconditions

- The person is resolved and their workspace is the working directory.
- Their own knowledge has been discovered and read.
- The conduct policy and the tool contract are in force.

## Steps

1. **Read the window** across the calendars that belong to them.
2. **Name what collides** — overlapping commitments, and back-to-back items in
   different places where travel makes the second impossible.
3. **Do the work they have authorized.** Creating, moving, cancelling and
   answering invitations are ordinary writes under the mandate rule: they
   execute when this ask, the invoked command's contract, or a standing
   instruction covers them, and are reported afterwards. Booking the focus block
   they always want, declining what their rules always decline, moving what they
   asked to move — none of these come back as questions.
4. **Propose the rest.** Where nothing grants authority, or where a collision
   trades one commitment against another, name the options precisely enough that
   a one-word answer settles it.
5. **Report once**, in the order the day runs: what is ahead, what was changed,
   what needs them.

## Outputs

- A briefing of the window with collisions and decisions named.
- Calendar changes made under mandate, each named in the report.
- Proposals for anything not covered.

## Recovery

- **A calendar cannot be read.** Say which one, and cover the rest rather than
  failing silently.
- **A change fails at the tool.** Report the failure with the event it concerned;
  do not retry through another route.
- **A collision has no obvious resolution.** Present it; the trade-off between
  two commitments is the person's.
- **An invitation involves other people and their rules do not cover it.**
  Propose; an answer sent on their behalf reaches those people.
