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

A record is opened when a run starts and closed when it ends. Records are only
ever added, never revised by a later run, so runs that overlap produce two
records rather than a contested one.

## Canonical fields

- **The window swept.** What the run considered: where it started, where it
  stopped, and whether it reached the end of what it set out to cover. A run that
  stopped early says so here rather than leaving it to be inferred.
- **What the window means once closed.** A closed window is the claim that
  everything in it was considered, written once the window is covered and never
  when the run begins. Whether a given message was considered is answered by
  whether some run's closed window contains it.
- **The judgement calls.** For messages where the answer was not obvious, what
  was decided and what made it close. Routine calls need no entry — a record that
  narrates every disposition is a second inbox.
- **What it could not decide.** The items handed to the person, with what would
  settle each. This is what a briefing is written from.
- **What went wrong.** Anything that failed, and whether the run continued past
  it. A run that ended badly reports through this record; it does not stay alive
  to be asked.
- **Its own state.** Whether the run is open or closed, and when it opened.
- **Whether its lessons have been folded in.** Set when what the person's handling
  taught has been written into what is known about their senders. Until it is set
  the record still has something to teach, and a later run can see that without
  reconstructing it.

## Allowed values

A record is **open** or **closed**. There is no third state: a run that died
without closing its record leaves an open one, and an open record older than a
run could plausibly take is a failed run rather than a live one — which is a
thing a later sweep can see and act on, where a silently missing record is not.

## Known caveats

- **Runs do not exclude each other.** Two sweeps may run at once. Each records
  what it covered and neither edits the other, so coverage is what their closed
  windows together contain. Nothing here is a lock, and an open record is not one:
  it says a run started, not that another may not.
- **Overlap is absorbed per message, not prevented.** Every action is checked
  against its own result, never against a record of having performed it: a reply
  is not drafted where a draft addressing that message already exists, and a
  disposition is not decided again where one already stands. No marker is written
  ahead of the work it describes.
- **A run that dies leaves its window open.** An unclosed window claims no
  coverage, and what it touched is read again by a later run. That re-reading is
  the recovery path. A failed run leaves work already done, never a claim that
  work was done.
- **It is kept only while it can still teach.** A record becomes disposable when
  it carries the mark saying its lessons were folded into what is known about the
  person's senders, and not before. An unmarked record is kept however old it is,
  and records surviving past their mark are disposed of.
- **It is not a report.** What the person receives is written from this record and
  shaped for them. The record is written for the next run.
- **A closed record is not a claim that the work was right.** It says what was
  done and why. Whether it was right is settled by what the person does next, and
  that correction arrives after the record is closed.
