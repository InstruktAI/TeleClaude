---
description: 'Per-project known-issue suppression ledger: an operator-authored allowlist of triaged error signatures that the log bug hunter subtracts before filing, written only through the telec bugs front door.'
visibility: 'public'
---

# Known-Issue Suppression — Spec

## What it is

A project's suppression ledger is an allowlist of error signatures that have
already been triaged, so an automated log scan does not file them again. It
lives beside the project's log-bug-hunter run state as a typed, versioned JSON
document with one entry per suppression. The ledger has exactly one writer, the
`telec bugs` front door, and its readers only ever read it. Run state, written
by the scan, is a separate file, so neither writer clobbers the other.

Each suppression carries the authored `pattern` and how to match it (`match` is
`substring` by default, `regex` on opt-in), a record-only `disposition`
(`expected` or `wontfix`, defaulting to `wontfix`), a human `reason`, an
optional `source_bug` slug naming the triage that produced it, creation
provenance, and an optional `expires_at`. A suppression is **active** while
`expires_at` is unset or in the future; an elapsed expiry is inert and its signal
is filed again.

Matching is a pure allowlist: the reader tests a candidate line against the
authored pattern and never grades whether a line is meaningful. A regex pattern
is validated at registration; one that fails to compile at read time is skipped,
never crashing the scan.

The operator surface is `telec bugs suppress "<pattern>" --reason <r>` with
optional `--match`, `--disposition`, `--project`, `--source-bug`, and
`--expires`; `telec bugs suppressions [--project <name>]` lists the ledger;
`telec bugs unsuppress <id>` removes one entry by the id assigned at
registration.

## Canonical fields

### Use cases

#### UC-KIS1: A fully suppressed window files nothing

```
Given a project's last-hour log window whose every candidate error line matches an active suppression
When the log bug hunter scans that window
Then no bug report is filed
And the window is recorded as seen and skipped
```

#### UC-KIS2: An unsuppressed signal among suppressed ones is still filed

```
Given a log window where some candidate lines match active suppressions and one does not
When the log bug hunter scans that window
Then the unmatched signal is filed
And the matched signals are recorded as suppressed, never filed
```

#### UC-KIS3: An elapsed expiry stops suppressing

```
Given a suppression whose expires_at is in the past
And a candidate error line matching its pattern
When the log bug hunter scans the window
Then the line is treated as unsuppressed and filed
```

#### UC-KIS4: An uncompilable regex never crashes the scan

```
Given a ledger entry with match = regex whose pattern no longer compiles
When the log bug hunter reads the ledger
Then that entry is skipped
And the scan continues with the remaining suppressions
```

#### UC-KIS5: The front door is the only writer

```
Given an operator registers a suppression with telec bugs suppress
When the log bug hunter next reads the project's ledger
Then the new suppression is honored
And the scan's own run-state write leaves the ledger file untouched
```

### Cross-context references

- **workflow** — a suppression's optional `source_bug` names the bug whose triage
  produced it; the bug lane owns that record.
- **software-development** — the consumer is the log-bug-hunter maintenance
  procedure, which subtracts active suppressions before filing.

## Known caveats

- A pattern should target the invariant signal (a stable reason token), not
  volatile values such as timestamps or identifiers, or it will never match twice.
- Disposition is record-only. `expected` and `wontfix` match identically; the
  value exists for the operator's audit, not for the scan.
