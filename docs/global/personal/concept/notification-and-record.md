---
description: The distinction that decides what a person's mail is worth — whether a message is the record of something or a notification about a record held elsewhere — and the handling that follows from it.
---

# Notification and Record — Concept

## What

Every message is one of two things. Either it **is** the record — the thing
itself, with no copy anywhere else — or it is a **notification** about a record
held somewhere else: an app, a portal, an account page, a system the person
already uses. Almost everything that matters about how to treat a message
follows from which one it is.

**Where the authoritative record lives elsewhere, the message is a
notification.** A booking, an order, a delivery, a social interaction — the
service holds the state and the person reads it there. The mail announces a
change to something it does not contain. It has no archival value at any point
in the sequence, first step or last, because nothing is lost by dropping it. The
service still knows.

**Where nothing else holds it, the message is the record.** Security and account
changes, credentials, invoices and receipts a person needs for accounting or
tax, contracts and legal documents, and anything from a party that has no portal
at all. Losing it loses the fact.

**Within records that move through states, only the terminal state survives.**
Ordered, shipped, delivered; requested, confirmed; issued, paid. The final state
implies the ones before it, so the intermediate steps carry nothing once it
arrives. This applies only where the message is the record; where the state is
held in a service, the whole sequence is notification and the terminal state is
no more valuable than the rest.

**A machine writing with no external system and no terminal state is a
notification stream.** Agent output, monitoring, scheduled reports. These are
worth removing, and worth ending at the source rather than removing forever.

**Anything a person wrote is never disposed of on judgement.** The cost of being
wrong about a human correspondent is asymmetric and, once a message is gone,
unrecoverable. Value is inferred for machines and asked about for people.

### What follows for handling

Volume is reduced at its source before it is managed. A notification stream that
recurs is ended by unsubscribing or by silencing it at the service; sweeping the
same sender forever is work that never finishes, and the person pays it every
time. This is the only move here with lasting effect.

Notifications are disposed of as they are recognised, not filed. Filing a thing
that carries no information spends a gesture to buy a shorter list, and a list is
not what anyone searches.

Records are kept and made findable. Findable means retrievable by search, not
sorted into a hierarchy — a person looking for last year's invoice searches for
it, and the folder it was in never helped.

One state carries one meaning. Where a person's unread flag means both "not yet
seen" and "not worth seeing", it tells them nothing at the moment they most need
it to. Reserving it for a single meaning is what makes it worth looking at.

### A caution about learning from history

Where most of a sender's mail has been disposed of and a few messages remain,
the survivors are far more likely to be inattention than deliberate exceptions;
a rule invented to explain the leftovers is a rule fitted to noise. Absence
teaches nothing at all — deleted mail leaves no trace, so what a person discards
is unlearnable in principle rather than merely missing.

What a person's mail does record is value: who they answer, how quickly, whom
they have never once answered, and which senders have ever caused them to act.
That evidence refines the classes above for one person. It does not establish
them, and a habit is not promoted to a practice by being observed.

## Why

Sorting mail by topic, sender reputation, or apparent urgency produces a
different answer for every service and generalizes to none of them. The
record-or-notification question generalizes, because it asks about the mail's
relationship to the truth rather than about its contents — and it is answerable
for a sender never seen before.

It also puts the effort where it lasts. Most of what arrives is notification,
so most handling effort is spent on mail that never needed handling. Reducing
that at the source is the only intervention that compounds; every other move
manages a volume that returns tomorrow.

The asymmetry between machine and human authorship is the safety rail that makes
the rest of it safe to automate. Every other distinction here can be wrong in
both directions at small cost; disposing of a person's letter cannot.

## See Also

- ~/.teleclaude/docs/personal/procedure/email-triage.md — where these classes are applied to a window of mail.
- ~/.teleclaude/docs/personal/spec/person-knowledge.md — the person's own priorities, which override these defaults wherever they speak.
