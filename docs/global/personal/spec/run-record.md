---
description: What a sweep leaves behind so the next one need not re-derive it — the reasoning a marker cannot carry, the point the sweep reached, and the claim that a run is still in progress.
---

# Run Record — Spec

## What it is

A sweep writes one record of itself. The dispositions it assigned say where each
message landed; the record says why, how far the sweep got, and what it could not
settle. Without it every run re-reads the whole history to reach conclusions the
last run already reached, which is the cost that makes an assistant not worth
running.

It lives in the person's workspace beside their knowledge, discovered by listing
rather than by name, like everything else there. It is the person's data and never
leaves their workspace.

A record is opened when a run starts and closed when it ends. An open record is
therefore also the statement that a run is underway, which is what lets a second
sweep know to defer rather than collide.

## Canonical fields

- **The window swept.** What the run considered: where it started, where it
  stopped, and whether it reached the end of what it set out to cover. A run that
  stopped early says so here rather than leaving it to be inferred.
- **The watermark it advanced to.** The point absence becomes meaningful up to.
  It is written once the window is genuinely covered, never at the moment the run
  begins, because a watermark written in advance claims coverage the run has not
  yet earned.
- **The judgement calls.** For messages where the answer was not obvious, what
  was decided and what made it close. Routine calls need no entry — a record that
  narrates every disposition is a second inbox.
- **What it could not decide.** The items handed to the person, with what would
  settle each. This is what a briefing is written from.
- **What went wrong.** Anything that failed, and whether the run continued past
  it. A run that ended badly reports through this record; it does not stay alive
  to be asked.
- **Its own state.** Whether the run is open or closed, and when it opened.

## Allowed values

A record is **open** or **closed**. There is no third state: a run that died
without closing its record leaves an open one, and an open record older than a
run could plausibly take is a failed run rather than a live one — which is a
thing a later sweep can see and act on, where a silently missing record is not.

## Known caveats

- **The record is the lease.** A sweep that finds an open record does not start a
  second one. This is what keeps two runs from both advancing the watermark, where
  the later timestamp would silently claim coverage of a window the earlier run
  never finished. Recording a standing instruction takes the same care for the
  same reason: the check that instructions do not conflict reads the whole set
  before writing to it, so two runs performing it at once can both pass and still
  produce the pair it exists to prevent.
- **It is kept only while it can still teach.** A record earns its place until the
  person's handling of its dispositions has been read back into what is known
  about their senders. After that its conclusions live in that durable knowledge
  and the record itself is disposable. Records that accumulate past this are the
  clerking the assistant exists to avoid.
- **It is not a report.** What the person receives is written from this record and
  shaped for them. The record is written for the next run.
- **A closed record is not a claim that the work was right.** It says what was
  done and why. Whether it was right is settled by what the person does next, and
  that correction arrives after the record is closed.
