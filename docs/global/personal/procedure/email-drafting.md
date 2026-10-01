---
description: Write a reply or a fresh message as the person, from the identity the correspondence belongs to — left as a draft, or sent when they ask for it to be sent.
activation_trigger: Use when replying to, composing, or sending mail on a person's behalf — including drafts prepared during triage.
---

# Email Drafting — Procedure

## Required reads

@~/.teleclaude/docs/personal/policy/assistant-conduct.md
@~/.teleclaude/docs/personal/spec/person-knowledge.md
@~/.teleclaude/docs/personal/spec/tools/gog-cli.md

## Goal

Produce a message that reads as the person — right identity, right voice, right
thread — and put it where they want it: waiting as a draft, or sent because they
asked for it to be sent.

## Preconditions

- The person is resolved and relevant identity context and voice examples have
  been discovered under `personal/spec/person-knowledge`.
- The conduct policy and the tool contract are in force.

## Steps

1. **Choose the identity.**
   - _Replying:_ send from the address the original was addressed to; the tool
     resolves this from the message when told to.
   - _Fresh outbound:_ choose from the identity registry by recipient and
     subject matter.
   - _Ambiguous:_ ask. Sending from the wrong identity discloses a relationship
     the correspondent was not part of.
2. **Match the voice of that identity.** Take the one or two examples closest to
   this identity and this kind of message, and write in that voice. If none of
   them fit the situation, write plainly instead of imitating a mismatched one.
3. **Apply the identity boundary** in `personal/policy/assistant-conduct` to
   the facts included in the draft. Surface any proposed cross-identity use.
4. **Compose as a draft**, in-thread with quoting when replying, with recipients
   carried forward correctly on a reply-all.
5. **Hand it over.** Tell the person where the draft is and what it says in one
   line.
6. **Carry out an authorized send** under `personal/policy/assistant-conduct`.
   When they ask for one to be sent: if they have seen
   the words, send it and report. If they have not — asking for a message to go
   out authorizes the errand, not the wording — show it once, then send on their
   word. One exchange, never a ceremony.
7. **When they tell you what they changed**, record it — as a standing
   instruction under `personal/policy/assistant-conduct` if they framed it as
   one, or as a voice example under `personal/spec/person-knowledge` when they
   identify a message as representative.

## Outputs

- A message in the person's mailbox from the correct identity and in the correct
  thread — waiting as a draft, or sent on their instruction and reported.
- Anything they stated about how they want it written, recorded once.

## Recovery

- **The identity is ambiguous and the registry does not decide it.** Ask; do not
  default to their primary address.
- **The tool refuses the operation.** Report it; do not reach for another route.
- **The reply would require cross-identity knowledge to make sense.** Flag that
  to the person and let them decide what may be said.
