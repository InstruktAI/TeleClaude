---
description: 'Per-project known-issue suppression ledger: an operator-authored allowlist of triaged error signatures that the log bug hunter subtracts before filing, written only through the telec bugs front door.'
visibility: 'public'
---

# Known-Issue Suppression — Spec

## What it is

A project's suppression ledger is an allowlist of error signatures that have
already been triaged, so an automated log scan does not file them again. It is a
typed, versioned JSON document with one entry per suppression, resolved per
project under the log-bug-hunter state directory. The ledger has exactly one
writer, the `telec bugs` front door; every other participant only reads it, so
nothing the scan does can clobber it.

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

A suppression's creation provenance is the principal the platform resolves for
the registering caller. A caller the platform cannot identify registers nothing.

Listing the ledger is a governed read: `telec bugs suppressions` is cleared
against its verb band in the process that runs it
(`local/projects/teleclaude/spec/feature/identity/command-clearance`, Local read clearance). The
bug hunter's role is admitted, so the log bug hunter reads the ledger it
subtracts before filing. A caller the platform cannot identify lists nothing.

## Canonical fields

### Use cases

#### UC-KIS1: A fully suppressed window files nothing

#### UC-KIS2: An unsuppressed signal among suppressed ones is still filed

#### UC-KIS3: An elapsed expiry stops suppressing

#### UC-KIS4: An uncompilable regex never crashes the scan

#### UC-KIS5: An operator can suppress a triaged signal without hiding new errors

```gherkin
Scenario Outline: Suppress a known signal and keep reporting other errors
  Given an operator has recorded a suppression for a triaged error
  And the next log window contains <signals>
  When the project's error report is prepared
  Then <outcome>

  Examples:
    | signals                                                 | outcome                                             |
    | only the matching suppressed error                     | no bug report is filed                              |
    | the suppressed error and a different unsuppressed error | only the unsuppressed error is filed                |
```

#### UC-KIS6: A suppression records the registering caller's resolved principal

#### UC-KIS7: A caller the platform cannot identify registers no suppression

#### UC-KIS8: The log bug hunter lists the ledger it subtracts

#### UC-KIS9: A caller the platform cannot identify lists no suppression

#### UC-KIS10: The ledger is the project's from anywhere inside it

### Cross-context references

- **workflow** — a suppression's optional `source_bug` names the bug whose triage
  produced it; the bug lane owns that record.
- **sdlc** — the consumer is the log-bug-hunter maintenance
  procedure, which subtracts active suppressions before filing.

## Known caveats

- A pattern should target the invariant signal (a stable reason token), not
  volatile values such as timestamps or identifiers, or it will never match twice.
- Disposition is record-only. `expected` and `wontfix` match identically; the
  value exists for the operator's audit, not for the scan.
