---
description: How an extraction worker turns one stretch of a help-desk conversation into memories — read it, judge what is worth remembering about the visitor and the business, discard what documentation covers, and record the survivors as one pass.
delivered_by:
  - help-desk-idle-memory-cycle
---

# Desk Memory Extraction — Procedure

## Required reads

- @docs/local/spec/feature/memory/conversation-extraction.md

## Goal

Record, as one pass, what a stretch of a help-desk conversation taught about the
visitor and about the business of the home that owns the desk — nothing the
documentation already says, nothing that is the agent's own commentary.

## Preconditions

- You were started by the daemon's idle cycle for one desk session. Your brief
  names the desk session, the pass key, the point in the conversation the pass
  starts after, the visitor's identity key and principal (or that the visitor
  has none), the desk's memory namespace and subject, and the home's memory
  namespace and subject.
- You record memories only through the pass you are about to record; you save
  no other memory.

## Steps

1. Read the desk session's conversation after the pass's starting point:
   `telec sessions tail <desk-session> --since <starting point> --full`. Read the
   visitor's and the desk agent's messages; tool activity and the agent's
   reasoning are not the conversation.
2. Note how far the conversation reaches: the timestamp of its newest message.
   That is how far your pass reaches.
3. Collect candidates through two lenses:
   - **About the visitor** — durable things worth knowing the next time this
     person writes: preferences, their situation, how they like to communicate,
     what they are still waiting on, what was promised to them. Only when your
     brief names an identity key for the visitor.
   - **About the business** — what the conversation shows the home that owns the
     desk: requests for what does not exist, complaints, recurring confusion,
     sentiment, mentions of alternatives.

   A candidate states something the conversation shows. Your own reading of the
   conversation, guesses about the visitor, and anything only the desk agent
   said without the visitor confirming it are not candidates.

4. For each candidate, search the desk home's documentation (`telec docs index`,
   `telec docs get`). Discard it when the documentation already covers it in
   substance, whatever its wording.
5. Record the survivors as one pass with
   `telec memories record-pass <pass key> --through <newest message timestamp>`,
   handing over the visitor candidates with the desk's namespace, subject, the
   visitor's identity key and principal, and the business candidates with the
   home's namespace and subject. Record the pass even when nothing survived: an
   empty pass completes the extraction of that stretch.
6. End your session.

## Outputs

- One recorded pass under the pass key, with its receipt.

## Recovery

- Recording is refused or fails: stop and end your session without retrying.
  The pass has no receipt, so the idle cycle starts a new worker for the same
  stretch later.
- The conversation cannot be read: end your session without recording; the same
  applies.
- The pass key already has a receipt: the stretch was extracted; end your
  session.
