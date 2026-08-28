---
description: The distinction that decides what a person's mail is worth — whether a message is the record of something or a notification about a record held elsewhere — and how to read a person's own handling of it.
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

### Reading a person's own handling

A person's history teaches these classes, but it has to be read as human
behaviour rather than as intent. Where most of a sender's mail has been disposed
of and a few messages remain, the survivors are far more likely to be
inattention than deliberate exceptions. A rule invented to explain the leftovers
is a rule fitted to noise.

Absence teaches nothing. Deleted mail leaves no trace, so what a person discards
is unlearnable in principle rather than merely missing — and where a person does
not prune at all, there is no corpus of discards to learn from however long they
have used the account. What their mail does record is value: who they answer,
how quickly, whom they have never once answered, and which senders have ever
caused them to act.

## Why

Sorting mail by topic, sender reputation, or apparent urgency produces a
different answer for every service and generalizes to none of them. The
record-or-notification question generalizes, because it asks about the mail's
relationship to the truth rather than about its contents — and it is answerable
for a sender never seen before.

It also explains what a person is doing when they leave hundreds of messages
unread and prune almost nothing. They are not neglecting a filing system; they
have correctly observed that most of their mail is notification, that
notifications need no filing, and that anything genuinely needed can be found by
searching. An assistant that treats that as disorder to be corrected has
misread a working strategy.

The asymmetry between machine and human authorship is the safety rail that makes
the rest of it safe to automate. Every other distinction here can be wrong in
both directions at small cost; disposing of a person's letter cannot.

## See Also

- ~/.teleclaude/docs/personal/procedure/email-triage.md — where these classes are applied to a window of mail.
- ~/.teleclaude/docs/personal/spec/person-knowledge.md — the person's own priorities, which override these defaults wherever they speak.
