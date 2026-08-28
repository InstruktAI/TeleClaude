---
description: The outcomes a sweep may assign to a message, the channel that carries them, and what a person's handling of that channel means back to the assistant.
---

# Mail Dispositions — Spec

## What it is

Every message a sweep considers leaves it with exactly one disposition. A message
the assistant could not decide about has the disposition for that, and a message
needing nothing carries no marker at all — which is legible only because each run
records the point it swept to.

A disposition is carried in a channel the assistant owns and nothing else writes
to. What that channel is belongs to the tool contract for the person's provider —
a label, a category, a folder — and the assistant never signals through a state
the person already uses for their own purposes. Reading and unread belong to the
person.

## Canonical fields

- **Exactly one.** Dispositions are mutually exclusive. A person acting on a
  message in one place has acted on it everywhere, and a message never appears
  under two proposals at once.
- **Absence is read against a watermark.** A message carrying no assistant marker
  is one of two things, and only the time a sweep last ran separates them: mail
  that arrived before that point was considered and needs nothing; mail that
  arrived after it has not been reached. Absence alone carries no meaning, and a
  claim that nothing is left unconsidered rests on the watermark being recorded,
  not on the marker being missing.
- **The reason lives elsewhere.** The disposition records where a message landed.
  Why it landed there belongs to the run record, which holds the reasoning the
  marker cannot and the watermark this absence is read against.

## Allowed values

- **Disposable — carries nothing.** No fact the person has a stake in.
- **Disposable — superseded.** Carries a stake, but the fact is held by a service
  and this message is not evidence of anything.
- **Disposable — stream.** One of a machine's recurring instances, where a later
  one carries everything this one did.
- **Needs the person.** The assistant could not decide, or a person wrote it, or
  what it touches is too costly to be wrong about.
- **Nothing proposed.** The message is the person's to keep and no action is
  suggested.

The set is closed. It follows the questions the classification asks, so it grows
only when those questions do — which is a change to shared doctrine, proposed to
an admin and never authored by a person's own assistant.

## Known caveats

- **The person's handling is the correction.** Disposing of something the
  assistant proposed disposing of confirms the call. Returning it to the inbox
  rejects it. A reply is the strongest endorsement available. These are the
  signals a later run learns from.
- **Only a finished gesture teaches.** A message left where the assistant put it
  says nothing about that message — it may have been postponed, avoided, or never
  looked at. A whole disposition whose items go persistently untouched says
  something about the disposition rather than about its members.
- **A disposition may graduate.** Where one has been sustained without correction
  and the cost of being wrong within it is survivable, its proposal may become an
  action taken rather than one offered. Sustained accuracy alone does not earn
  this; a disposition that could hold something irreplaceable does not graduate
  however clean its record.

## See Also

- ~/.teleclaude/docs/personal/spec/run-record.md — the record carrying the reasoning, the watermark, and the claim that a sweep is in progress.
