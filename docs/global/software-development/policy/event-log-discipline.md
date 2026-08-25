---
id: software-development/policy/event-log-discipline
type: policy
domain: software-development
scope: global
description: Keep immutable event history readable across code evolution while cursor-driven delivery drains safely.
delivered_by: [reminder-history-tolerant-reader]
---

# Event Log Discipline — Policy

## Rules

### Immutable history is read, never repaired

- An append-only event or source-entry record is audit truth. A newer build does
  not delete, migrate, rewrite, or reinterpret an old record merely because its
  executable vocabulary changed.
- Archive and history surfaces are render-only. They present the record's stored
  prose and open metadata; membership in a current registry never decides whether
  a historical record is readable.

### Durable readers are tolerant

- Values whose executable registry may narrow over time are open metadata on
  read. A closed type may validate a new write or select a current handler, but
  it never rejects an authentic stored value because the current build no longer
  registers it.
- A curated registry is a lookup surface, not the historical field's type. An
  unknown or retired stored identity follows the generic presentation path.
- Durable entries carry the self-contained prose needed for presentation plus
  open metadata. A reader never asks current code to reconstruct the meaning of
  prose the writer could have stored at creation time.

### Cursor-driven consumers always drain

- A cursor-to-now consumer classifies failures at the record boundary. A
  record-local interpretation failure is permanent for that immutable record:
  log the stable row identity, skip the record, and advance the cursor.
- A downstream delivery failure is transient: leave the cursor before that
  record so the existing delivery path can retry it.
- One record's permanent failure never aborts the whole read window, blocks later
  records, escapes into an unrelated parent loop, or becomes user-facing internal
  error feedback.

## Rationale

Executable registries evolve; immutable history does not. Coercing stored values
through today's registry turns ordinary code retirement into a delayed poison
message. When archive storage also feeds a delivery cursor, retrying that same
immutable record can freeze every later record forever. Tolerant interpretation
preserves audit truth, while the permanent/transient discriminator lets the queue
drain without treating a real delivery outage as success.

## Scope

Applies to append-only event, audit, source-entry, and projection streams whose
records outlive the executable code that wrote them.

## Enforcement

- Review rejects a historical read that coerces an evolving stored identity
  through a current closed registry.
- Review rejects an all-or-nothing cursor window in which one record-local decode
  failure prevents later records from being considered.
- Review rejects cursor advancement after a failed downstream handoff and rejects
  retrying a permanently unreadable immutable record.
- Permanent failure evidence names the stable record identity and contains no
  stored prose or other sensitive body content.

## Exceptions

None. A separately versioned upcaster may transform structure at the read
boundary, but it never mutates the source record or makes current registry
membership a historical validity rule.
