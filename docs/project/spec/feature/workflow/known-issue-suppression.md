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
(`project/spec/feature/identity/command-clearance`, Local read clearance). A
job-runner session is admitted, so the log bug hunter reads the ledger it
subtracts before filing. A caller the platform cannot identify lists nothing.

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
And no participant other than the front door has written to the ledger file
```

#### UC-KIS6: A suppression records the registering caller's resolved principal

```
Given an operator at a logged-in terminal, or an agent in a session carrying a principal
When they register a suppression with telec bugs suppress
Then the entry's creation provenance names the principal the platform resolved for that caller
```

#### UC-KIS7: A caller the platform cannot identify registers no suppression

```
Given a process the platform cannot identify
When it runs telec bugs suppress
Then no entry is written to the ledger
And the refusal names how to establish an identity
```

#### UC-KIS8: The log bug hunter lists the ledger it subtracts

```
Given a project whose ledger holds active suppressions
When the log bug hunter, running as a job-runner session, runs telec bugs suppressions for that project
Then every active entry is listed
```

#### UC-KIS9: A caller the platform cannot identify lists no suppression

```
Given a project whose ledger holds active suppressions
And a process the platform cannot identify
When it runs telec bugs suppressions for that project
Then no entry is listed
And the refusal says why the caller is not identified
```

<!-- planned:worktree-or-project-scope -->
#### UC-KIS10: The ledger is the project's from anywhere inside it

```
Given an operator or agent standing in a subdirectory, or in a slug worktree, of a project
When they register, list, or remove a suppression without naming a project
Then the command acts on that project's ledger, the one the log bug hunter reads for the project
And no ledger keyed on a worktree's copy of the project declaration is read or written
```
<!-- /planned:worktree-or-project-scope -->

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
