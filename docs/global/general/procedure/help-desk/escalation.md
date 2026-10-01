---
description: How a help-desk agent hands a visitor to the admins of the home that
  owns the desk, and how it resumes after an admin hands the conversation back.
visibility: public
---

# Help Desk Escalation — Procedure

## Goal

Connect the visitor with a person accountable for the home they came to, and
continue the conversation informed by what that person settled.

## Preconditions

- The session runs in a help desk. Escalation from anywhere else is refused.
- The visitor asked for a person, or the question needs someone's authority, or
  the documentation cannot answer something that matters to them.

## Steps

1. Tell the visitor you are bringing in a person. If you do not know how they
   want to be addressed, ask.
2. Run `telec sessions escalate --customer <name> --reason <why a person is
needed> --summary <what has been established so far>`. The platform adds
   which desk this is and how to reach the visitor; the admins of the home that
   owns the desk are notified.
3. Tell the visitor a person will answer them here, in this conversation. From
   now on their messages go to that person, not to you.
4. When the conversation is handed back, you receive the exchange between the
   admin and the visitor. Read it, continue from where it ended, and do not ask
   the visitor to repeat what they already told the admin.

## Outputs

- An escalation the owning home's admins can act on, naming the desk, the
  visitor and the reason.
- After hand-back, a conversation that continues from the admin's exchange.

## Recovery

- The escalation is refused or fails: tell the visitor no one can be reached
  right now, keep helping with what the documentation covers, and promise no
  callback.
