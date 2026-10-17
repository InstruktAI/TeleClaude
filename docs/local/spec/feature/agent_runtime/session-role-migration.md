---
description: The one-time forward migration that gives every stored session one catalog
  role — mapping recorded role and job pairs explicitly, reducing the job field to
  instance identity, keeping unmappable rows refused and reported, migrating persisted
  launch state with the sessions, and leaving every occurrence label as the provenance
  it recorded.
---

# Session Role Migration — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

Sessions recorded before roles were composed in the catalog carry a system role
and a job whose combination named their assignment. The migration runs once,
forward, when the runtime that reads one role per session first starts. It
inventories every distinct recorded combination, maps the combinations the
catalog can name through an explicit table, reduces the job field to the
instance identity a scheduled run or an activation carries, and leaves every
other row with its original representation recorded, refused at runtime and
reported. It migrates the persisted launch state that drives a session's continuation beside the sessions. Everything that records who acted at an occurrence — the labels on
authored turns and the caller snapshots on queued inputs — is provenance: it
keeps its recorded value and is never re-derived from a session's migrated
role; the session mirrors keep their own
record under their own contract
(`local/projects/teleclaude/spec/feature/session_mirrors/historical-conversation-search`).

Rollback is the pre-migration deployment restored together with its data; the
old readers are never run against migrated fields.

## Canonical fields

### Mapping

| Recorded combination                                                                    | Result                                                                                                                                                                                                                                                                        |
| --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| a command session whose job is a role the catalog keeps (builder, reviewer, planner, …) | role := that job; job := empty                                                                                                                                                                                                                                                |
| `job_runner` with a job naming a configured scheduled job                               | role := the role that job's procedure declares; job := the job name                                                                                                                                                                                                           |
| `job_runner` with a job naming a procedure                                              | role := the role that procedure declares; job := the configured job's name when one job names that procedure, otherwise unmappable                                                                                                                                            |
| `tasker` with `task-preparer` or `task-runner`                                          | role := that value; job := empty                                                                                                                                                                                                                                              |
| `tasker` with a job naming a procedure                                                  | role := the role that procedure declares; job := the procedure ID                                                                                                                                                                                                             |
| `integrator` or `coordinator`, including the legacy `(orchestrator, coordinator)` pair  | role := that name; job := empty                                                                                                                                                                                                                                               |
| a recorded command naming a retired lifecycle, creative, general or personal command    | command := the entry procedure that command's retirement companion maps it to, one target per command                                                                                                                                                                         |
| a recorded command naming the retired `general/run-job`                                 | command := the procedure the row's job resolves to — a procedure ID recorded in `job` is itself the evidence; a job name resolves through the current declaration carrying it, and the ledger records which declaration was used; a name no declaration carries is unmappable |
| a recorded command naming the retired `general/activate-procedure`                      | command := the procedure ID recorded in `job`, which an activation always carried                                                                                                                                                                                             |
| a roleless session                                                                      | unchanged                                                                                                                                                                                                                                                                     |

The table reads the recorded values as the runtime that wrote them read them:

- A row is roleless only when it records no system role, no working slug, and
  no `coordinator` job. A row with no recorded system role and a working slug
  is not roleless: it is read as a `worker` row with the job it records, and
  with no job the catalog names it is unmappable.
- A recorded system role and job agree with the row's recorded command when
  they are the pair that command conferred at launch, or a pair an in-place
  adoption door writes over any command: lane adoption into preparation or
  work, and coordinator acquisition. The legacy `(orchestrator, coordinator)`
  pair agrees with the retired coordinate command; a `job_runner` row agrees
  with the retired `general/run-job` or with no command; a `tasker` row whose
  job names a procedure agrees with the retired `general/activate-procedure`.
  A row with no recorded command agrees only through an adoption door's pair.
  Every other pairing is a conflicting triple.
- A job naming a standing role makes a standing row only under that standing
  role's own system role or the legacy `(orchestrator, coordinator)` pair. A
  `job_runner` row is read by the `job_runner` rows of the table whatever its
  job is called.
- A command mapping the table cannot complete makes the row unmappable,
  whatever its role mapping.

A combination the table does not name — an obsolete job such as a reviewer
kind the catalog no longer keeps, a conflicting role, job and command triple,
a procedure that declares no role — is unmappable. The migration writes the
reserved value `unmapped` into the row's role field, a value the catalog never
names, so every consumer resolves it to the unknown-role refusal and never to a
roleless session or a valid role; it records the row's original values and the
reason in the migration ledger, which is the report an operator reads. The
evidence the migration reads is the row's own recorded values and, for a job
name, the declaration currently carrying that name; no other history exists,
so a binding the row does not record is not inferred. Nothing is elevated by
title or prose. Persisted launch intents that belong to a row are migrated to that row's
result, `unmapped` included; queued caller snapshots keep their recorded
labels as provenance (UC-SRM3).

### Declarations at the cutover

The procedure a row resolves to and the job declarations its job name resolves
through are read for the canonical checkout of the row's project, never for a
linked todo worktree the row was recorded in. The role such a row takes is the
one the entry declaration in force at this cutover names, as `context` answers
the declaration state for that checkout: the declaration the procedure's live
document carries, or, while the delivery that ships the migration has not yet
folded its documentation, the declaration pending in that same delivery. The
code reaches the canonical checkout before its documentation folds, and the
migration runs at whichever start comes first; it neither waits for the fold
nor holds the runtime down until it lands
(`local/projects/teleclaude/policy/daemon-availability`). A declaration pending
only in another delivery, or none, is a procedure that declares no role. The
report records, for each such mapping, whether the declaration was live or
pending.

A declaration source the mapping needs and cannot read — the documentation
publishers, or the job configuration of a project whose checkout exists — makes
the migration not ready: it stops before the report or any row changes, its
error names the unreadable source, the migration stays unrecorded, and the next
start runs it again. A project whose checkout no longer exists carries no job
declaration.

### Continuation of migrated sessions

A session recorded before the migration has no persisted resolved invocation.
When such a session is continued — restarted, revived, or handed off — the
runtime reconstructs the invocation from the row's retained evidence and
composes its loader from it: the procedure is the row's migrated command;
the `slug` parameter is the row's working slug; a job entry's context is the
job name the row carries; an activation's context is the procedure ID the row
carries with the subject binding and delivery settings recorded on the
session. A required input the row does not retain — a non-slug argument such
as a research brief or a commit list, an activation home the records no
longer resolve — is not invented: the continuation is refused naming the
missing input, the refusal is logged, and the row keeps its migrated role so
the session stays inspectable.

### Use cases

#### UC-SRM1: Mappable rows take one role

#### UC-SRM2: An operator can diagnose an unmappable session without losing it

```gherkin
Given an operator upgrades TeleClaude and a stored session has a combination the migration cannot map
When the session-role migration completes
Then the session's original record is preserved and reported as unmappable with its values and reason
And role-gated actions on it are refused rather than assigned a valid role
```

#### UC-SRM3: Historical attribution is provenance, not derivation

#### UC-SRM5: A migrated session continues from reconstructed evidence or is refused

```gherkin
Given an operator asks a session recorded before the migration to continue from its retained work evidence
When the session restarts, revives, or is handed off
Then it resumes from the procedure and context the record supports
And if required input is missing, continuation is refused with that input named and the migrated role unchanged
```

#### UC-SRM4: An operator can inspect the one-time session migration result

```gherkin
Given an operator upgrades TeleClaude to the catalog-role runtime
When the runtime migrates stored sessions
Then the operator can read which sessions were migrated before any row changes
And an interrupted migration leaves the recorded rows unchanged
And later starts do not rerun a completed migration
```

#### UC-SRM6: A combination that disagrees with itself elevates nothing

#### UC-SRM7: A declaration not yet folded maps as its delivery publishes it

#### UC-SRM8: An operator can diagnose a blocked session migration

```gherkin
Given an operator upgrades while a required job or role declaration source is unreadable
When the session-role migration starts
Then it stops before the report or any session row changes
And the error names the unreadable source
And a later start retries the migration
```

#### UC-SRM9: A row recorded in a todo worktree resolves against the canonical checkout

### Cross-context references

- **identity** — owns the catalog the mapping resolves roles against and the refusal of an unknown recorded role.
- **context** — answers which entry declaration a checkout holds for a procedure — live, pending in a named delivery, or none — and reports an unreadable source; the job-runner and tasker rows resolve their role through that answer.
- **config** — owns which scheduled job names which procedure.
- **session_mirrors** — owns the mirror store's own classification and attribution records.

## Known caveats

- Which procedure an old scheduled job ran is established by the row's recorded procedure ID where it names one, otherwise by the declaration currently carrying the row's job name; the ledger records which, and a changed pointer in the meantime is not detectable from the row.
- A row marked unmappable is a defect to resolve by an operator reading the
  report; the migration never guesses.
- A procedure whose role is pending only in another delivery declares no role
  at this cutover, so its rows are unmapped and reported even after that
  delivery folds.

## See Also

- docs/local/spec/feature/identity/agent-roles.md
- docs/local/spec/feature/agent_runtime/procedure-entry.md
