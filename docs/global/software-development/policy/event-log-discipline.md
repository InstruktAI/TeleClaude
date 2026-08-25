---
description: Keep immutable event history readable across code evolution while cursor-driven delivery drains safely.
delivered_by:
  - reminder-history-tolerant-reader
---

# Event Log Discipline — Policy

## Rules

### Immutable history is open on read

- A record in an immutable append-only store is historical data produced by the
  writer that existed at that instant. Readers accept its stored values without
  coercing them through the current build's closed enums, registries, or
  prescribed-name types.
- Closed vocabularies validate new writes and current registry lookups only.
  Values recovered from durable history remain open data. An unknown or retired
  value is preserved as its stored value or resolved through an explicit generic
  presentation path; it is never a read error merely because current code no
  longer declares it.
- Agent-presented entries are self-contained at write time. Their durable prose
  and open metadata remain sufficient for later display without consulting the
  writer's current registry or reconstructing old intent from present code.
- Immutable history is not deleted, rewritten, or migrated to repair a current
  reader. Compatibility is restored at the read boundary. Where a structural
  version genuinely needs translation, a pure versioned upcaster may adapt the
  read result without mutating the source record.

### Delivery windows and archives have different duties

- A live consumer reads only its cursor-to-now window. The cursor is delivery
  state, not an invitation to replay the archive or reinterpret records already
  behind it.
- A record-local permanent failure cannot hold a live cursor. The consumer logs
  the stable record identity and failure, skips that record, and advances so
  later records remain reachable.
- A transient downstream failure may hold the cursor only when retry can change
  the outcome, such as a temporarily unavailable delivery surface. Permanent
  decode or compatibility failures and transient delivery failures are explicit
  distinct outcomes.
- Archive and history surfaces render the stored record as written through a
  tolerant reader. They do not use current domain vocabulary to decide whether
  an historical record is valid.
- Replay or read-model rebuilding is an explicit, versioned operation justified
  by a consumer that needs reconstruction. It is never hidden inside the live
  polling path.

### Projection failure stays contained

- One malformed or incompatible record degrades only that record's projection.
  It does not terminate the polling coordinator, stall unrelated sessions, or
  surface an internal projection exception as a user-facing operation failure.
- Boundary logs carry enough stable record and consumer identity to diagnose the
  skipped projection without copying sensitive payload content.

## Rationale

Immutable records outlive the code and vocabularies that produced them. A reader
that treats today's declarations as yesterday's schema makes normal code cleanup
retroactively corrupt history. Cursor-driven delivery compounds the defect: a
single permanent poison record becomes an infinite retry loop and prevents every
later record from being observed.

Separating live queue semantics from archive semantics preserves both duties.
The live window drains, while the archive remains complete audit truth. Read-side
tolerance keeps compatibility at the only boundary that can change when the
underlying store cannot.

## Scope

Applies to immutable append-only event, transcript, and history records that
outlive the writer build, plus cursor-driven consumers and renderers that read
them.

## Enforcement

- Review rejects reads of durable historical values through current closed
  vocabularies unless a versioned migration boundary has already converted the
  value before domain code sees it.
- Review rejects a cursor path that retries a permanent record-local failure or
  lets one projection error terminate a wider polling loop.
- Verification demonstrates that unknown historical values remain readable,
  permanent poison records do not block later records, and transient delivery
  failures retain their retry behavior.

## Exceptions

- A store wholly owned by the project may migrate forward under the owned-data
  regime instead of retaining open historical values. That migration completes
  before current domain code reads the record.

## See Also

- ~/.teleclaude/docs/software-development/policy/backward-compatibility-hygiene.md
