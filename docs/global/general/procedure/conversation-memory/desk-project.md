---
delivered_by:
  - help-desk-idle-memory-cycle
description: Keeps the memories about a project help-desk visitor current when
  their desk session ends — one agent per desk session, returned to by that
  session's later ends.
subscriptions:
  - teleclaude.agent_runtime.session.ended.help_desk
subscription_home: project
subscription_identity: subject
---

# Project Desk Conversation Memory — Procedure

## Required reads

- @~/.teleclaude/docs/general/procedure/conversation-memory/overview.md

## Goal

When a help-desk session at this project's desk ends, keep the memories about
its visitor at that desk current and collect the business items the conversation
showed, as the conversation memory procedure describes. This agent serves one
desk session: a later end of the same session, after its visitor revived it,
returns to this agent with its own context.

## Preconditions

- Activated by the end of a help-desk session at this project's desk, working in
  the project's checkout.

## Steps

1. Run the conversation memory procedure for the ended session, through
   advancing its read point.
2. End this session: `telec sessions end self`. The desk session's next end
   revives this agent with its context.

## Outputs

- The outputs of the conversation memory procedure for this desk session.

## Recovery

- Recovery follows the conversation memory procedure. A run ended by its
  recovery still ends this session, so the next end of the desk session revives
  this agent to read the same stretch again.
