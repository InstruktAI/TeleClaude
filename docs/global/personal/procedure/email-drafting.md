---
description: Write a reply or a fresh message as the person, from the identity the correspondence belongs to, and leave it as a draft.
activation_trigger: Use when replying to or composing mail on a person's behalf — including drafts prepared during triage.
---

# Email Drafting — Procedure

## Required reads

@~/.teleclaude/docs/personal/policy/assistant-conduct.md
@~/.teleclaude/docs/personal/spec/person-knowledge.md
@~/.teleclaude/docs/personal/spec/tools/gog-cli.md

## Goal

Produce a draft the person can send unedited: right identity, right voice, right
thread — and never sent by the agent.

## Preconditions

- The person is resolved and their identity registry and examples have been read.
- The conduct policy and the tool contract are in force.

## Steps

1. **Choose the identity.**
   - *Replying:* send from the address the original was addressed to; the tool
     resolves this from the message when told to.
   - *Fresh outbound:* choose from the identity registry by recipient and
     subject matter.
   - *Ambiguous:* ask. Sending from the wrong identity discloses a relationship
     the correspondent was not part of.
2. **Match the voice of that identity** — its language and register — using the
   person's approved examples rather than a generic tone.
3. **Write as the receiving identity.** Use only what this identity plausibly
   knows of this correspondent. Where knowledge that arrived through another
   identity would materially help, flag it to the person instead of using it.
4. **Compose as a draft**, in-thread with quoting when replying, with recipients
   carried forward correctly on a reply-all.
5. **Hand it over.** Tell the person where the draft is and what it says in one
   line. The draft is the proposal; sending is theirs.
6. **When they tell you what they changed**, record it — as a standing
   instruction if they framed it as one, or as an example of their voice.
   Recording happens because they said something, never by inspecting what they
   sent.

## Outputs

- A draft in the person's mailbox, from the correct identity, in the correct
  thread.
- Anything they stated about how they want it written, recorded once.

## Recovery

- **The identity is ambiguous and the registry does not decide it.** Ask; do not
  default to their primary address.
- **The tool refuses the operation.** Report it; sending is not an alternative.
- **The reply would require cross-identity knowledge to make sense.** Flag that
  to the person and let them decide what may be said.
