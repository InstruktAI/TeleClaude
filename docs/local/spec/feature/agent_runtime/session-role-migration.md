---
description: The one-time forward migration that gives every stored session one catalog role — mapping recorded role and job pairs explicitly, reducing the job field to instance identity, keeping unmappable rows refused and reported, migrating persisted launch state with the sessions, and leaving every occurrence label as the provenance it recorded.
delivered_by:
  - procedure-role-capability-composition
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
  held the worker role, and is read as a worker row with the job it records.
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

### Continuation of migrated sessions

A session recorded before the migration has no persisted resolved invocation.
When such a session is continued — restarted, revived, or handed off — the
runtime reconstructs the invocation from the row's retained evidence and
materializes the brief from it: the procedure is the row's migrated command;
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

```gherkin
Given a session recorded with a system role and a job the mapping names
When the migration runs
Then the session carries the mapped role and the job field holds only its instance identity, or nothing
And its persisted launch state carries the same role
```

#### UC-SRM2: Unmappable rows are kept, refused and reported

```gherkin
Given a session recorded with a combination the mapping does not name
When the migration runs
Then the row keeps its recorded job and command and carries the reserved `unmapped` role
And the migration's report names the session, every original recorded value and the reason
And an agent reviving that session is refused every role-gated act with the not-permitted failure naming the recorded role
```

#### UC-SRM3: Historical attribution is provenance, not derivation

```gherkin
Given authored turns and queued inputs recorded with a job-role label before the migration
When the migration runs
Then each keeps its recorded label as the provenance of that occurrence
And no label is rewritten from the session's migrated role
```

#### UC-SRM5: A migrated session continues from reconstructed evidence or is refused

```gherkin
Given a session recorded before the migration whose row retains its command, working slug and instance identity
When an agent restarts, revives or hands off that session
Then the loader it receives names a brief materialized from the reconstructed invocation
And given a row whose required input is not retained
When the same continuation is attempted
Then it is refused naming the missing input and the row's migrated role is unchanged
```

#### UC-SRM4: The migration runs once and is observable

```gherkin
Given the runtime starts for the first time after the migration is deployed
When it opens the session store
Then the migration runs before any role-gated act is served
And its inventory and report are written where an operator can read them before any row changes
And an interrupted run leaves every row as it was recorded
And a later start finds the migration recorded and does not run it again
```

#### UC-SRM6: A combination that disagrees with itself elevates nothing

```gherkin
Scenario Outline: Disagreeing recorded values are unmappable
  Given a session recorded as <combination>
  When the migration runs
  Then the row carries the reserved `unmapped` role
  And the report names the session, its recorded values and the reason
  And no role-gated act is admitted for the session

  Examples:
    | combination                                                                      |
    | a `job_runner` whose job is `integrator` and that no configured job carries      |
    | a `worker` whose job is `builder` under a command that conferred `reviewer`      |
    | no recorded system role, a working slug and no job                               |
    | an adoption pair under a retired `general/run-job` whose job no declaration carries |
```

### Cross-context references

- **identity** — owns the catalog the mapping resolves roles against and the refusal of an unknown recorded role.
- **context** — publishes each procedure's declared role, which the job-runner and tasker rows resolve through.
- **config** — owns which scheduled job names which procedure.
- **session_mirrors** — owns the mirror store's own classification and attribution records.

## Known caveats

- Which procedure an old scheduled job ran is established by the row's recorded procedure ID where it names one, otherwise by the declaration currently carrying the row's job name; the ledger records which, and a changed pointer in the meantime is not detectable from the row.
- A row marked unmappable is a defect to resolve by an operator reading the
  report; the migration never guesses.

## See Also

- docs/local/spec/feature/identity/agent-roles.md
- docs/local/spec/feature/agent_runtime/procedure-entry.md
