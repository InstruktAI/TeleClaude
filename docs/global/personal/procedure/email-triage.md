---
description: Review a person's inbox, act only within mandate, and give them one briefing of what arrived and what awaits them.
activation_trigger: Use when the person asks what is in their inbox, asks to triage, clear, or catch up on mail, or when a scheduled run of their assistant covers their mail.
---

# Email Triage — Procedure

## Required reads

@~/.teleclaude/docs/personal/policy/assistant-conduct.md
@~/.teleclaude/docs/personal/spec/person-knowledge.md
@~/.teleclaude/docs/personal/spec/tools/gog-cli.md

## Goal

Turn an inbox into one briefing the person can read in a minute: what arrived,
what was handled, what needs them.

## Preconditions

- The person is resolved and their workspace is the working directory.
- Their own knowledge has been discovered and read.
- The conduct policy and the tool contract are in force.

## Steps

1. **Fetch the window.** Search their mail for the period being reviewed —
   since the last briefing, or the period they named.
2. **Check provenance before acting on anything.** Compare each message's From
   against its Reply-To and its sending domain. A mismatch is reported in the
   briefing as suspected forgery and is not answered, labelled, or archived.
3. **Sort against their priorities.** Who always matters, what is always noise,
   what they want surfaced rather than handled. Where their rules do not decide
   it, it goes to the briefing rather than being guessed.
4. **Act only within mandate.** Labelling and archiving happen when a standing
   instruction or this invocation covers them. Everything else is proposed in
   the briefing, named precisely enough that "yes" is a complete answer.
5. **Prepare replies their rules call for**, following the drafting procedure.
   Drafts are prepared, never sent.
6. **Report once.** What arrived, what was done, where the drafts are, what
   awaits them, and what is proposed. One briefing, not a running commentary.

## Outputs

- A briefing covering the window.
- Any drafts prepared, identified so the person can open them.
- Triage operations applied under mandate, named in the briefing.

## Recovery

- **The person cannot be resolved.** Do not touch mail. Say which identity is
  missing.
- **A command is refused by the tool.** Report the refusal. Do not look for
  another route.
- **Their priorities do not decide a message.** Propose; never guess on their
  behalf.
- **Authorization is missing or expired for an account.** Say so and name the
  account; do not silently skip it.
