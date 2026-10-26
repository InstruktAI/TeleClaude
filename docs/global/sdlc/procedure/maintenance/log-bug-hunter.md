---
description: 'Proactive log-scanning job that discovers daemon errors and files a minimal bug report for each unsuppressed signal.'
visibility: 'public'
role: bug-hunter
dispatch:
  agent: [codex, claude, gemini]
  thinking_mode: med
---

# Log Bug Hunter — Procedure

## Required reads

- @~/.teleclaude/docs/sdlc/concept/defect-evidence.md
- @~/.teleclaude/docs/sdlc/policy/todo-creation-discipline.md
- @~/.teleclaude/docs/general/procedure/scheduled-job-run.md

## Goal

Scan the current project's logs, reject warnings and exclude errors attributable to
congestion, a computer restart, or an upstream dependency's own failure. File only errors
whose records support a failure in the scanned project's own handling through
`telec bugs report`. The bug lifecycle owns diagnosis and implementation.

## Preconditions

- The runner started this session in the target project for a job declaration
  whose `job` pointer names this procedure; the declaration's `name` is the job
  identity.
- The project's log name and the job's schedule are available from its configuration.
- `instrukt-ai-logs`, `telec bugs suppressions`, `telec bugs list`,
  `telec todo list`, `telec todo artifacts read`, `telec docs index`, `git`,
  and `telec bugs report` are available.

- The latest per-job JSON file at `STATE_DIR/runs/<project_slug>/<job_name>.json` carries the generic outcome envelope and this procedure's checkpoint in its `state` object. Read that object when resuming. This procedure owns the checkpoint schema under Outputs; the reporting command treats it as opaque JSON. Submit the outcome and complete replacement object through one `telec jobs report` invocation.

## Steps

<!-- @include: docs/snippets/step-role-read.md -->

1. Establish the scan window for this project.
   - Read the saved envelope's `state` object using the schema under Outputs. A missing file or absent checkpoint uses the first-run defaults. A present checkpoint that cannot be read or does not match this procedure's schema follows Recovery.
   - If `incomplete_scan` is present, retry its recorded start/end window. Otherwise, fix the end at the current UTC time and start at `completed_until`; with no completed cursor, start one declared schedule interval before that end. Process records in the half-open interval `[start, end)`. A completed window advances the next start to its end.

   - Collect that window with
     `instrukt-ai-logs {project_slug} --since <window>`.
     A successful empty result is a clean scan. A failed collection is an
     incomplete scan, reported under Recovery.

2. Establish which records are eligible to become signals.
   - Under `sdlc/policy/observability`, only `ERROR` and `CRITICAL`
     records, exceptions, and tracebacks are filing candidates. A `WARNING` never becomes
     a signal or bug report, however often it repeats. Adjacent warnings may be read only as
     context for an eligible error; they are not findings and are omitted from the report.
   - Group related eligible records into distinct error signals. Use the observed messages
     and context; do not investigate the codebase to establish a diagnosis.
   - Establish which system owns the failed operation. An upstream 5xx response, rate limit,
     timeout, or connection reset is an external failure and does not by itself establish a
     defect in the scanned project. Exclude the upstream failure unless records also show that
     the scanned project violated a supported contract in handling it, such as a required
     retry or recovery not occurring; cite that contract. When ownership or the local handling
     outcome is unknown, exclude the signal as causally inconclusive. An ERROR level, a failed
     delivery, or the absence of a matching suppression does not establish a local defect
     (`sdlc/policy/todo-creation-discipline`, `general/policy/human-contract`).
   - Before an error signal may proceed, falsify both operational explanations: congestion
     and a computer restart. Correlate its timing and surrounding records with the available
     restart evidence, resource-pressure or backlog evidence, and subsequent recovery. The
     filing burden is positive: absence of evidence for congestion or restart is not evidence
     against them.

   - When congestion or a computer restart explains the error, exclude it. When the available observations cannot rule out either cause, exclude it as causally inconclusive. Do not create a bug to obtain the missing causal evidence.

3. Deduplicate each error signal that passed the eligibility and causal gates.
   - Read `telec bugs suppressions` for the project. Match only active entries,
     using each entry's declared substring or regex semantics. Record matches
     with their suppression IDs. Skip an invalid regex and record that error.
   - Suppressions deduplicate specific signals already triaged as accepted recurring noise;
     they do not establish defect ownership or causal eligibility. Handle an upstream
     failure at the causal gate rather than adding a broad suppression for external errors.
     A recurring signature belongs in suppression only after separate triage establishes that
     it is accepted noise.
   - Read `telec bugs list` and `telec todo list`. These return slugs, and a
     slug names work rather than a mechanism, so a signal that matches no slug
     is not thereby untracked. Select candidates by token overlap between the
     signal — its message, its implicated module or file, and any subsystem or
     agent it names — and the returned slugs, then read those candidates'
     artifacts with `telec todo artifacts read <slug> <name>` before concluding
     a signal is untracked. Read the selected candidates only; the active set is
     never read in full. Record a matching active bug or todo by its slug
     instead of filing a duplicate.
   - Establish whether the implicated code has changed since the signal fired,
     keyed on the path the signal already carries. On the project's main branch,
     `git log --since=<last occurrence> -- <path>`: a change there after the
     signal last fired means the failure is likely already repaired, whether or
     not any todo records it. Do not file; carry the signal to the next run and
     file only if it recurs afterwards. On each active branch,
     `git log <branch> --since=<first occurrence> -- <path>`, together with
     `telec docs index --target <slug>` for a pending contract on that path: a
     match means in-flight work owns the mechanism. Record that slug and do not
     file a sibling.

- Delivered, closed, and removed work is not read. Whether a past failure was
  repaired is answered by the code and its history above, which is the source
  of truth for that question (`general/principle/grounding`); a record of
  completed work is neither, and its size grows without bound while its
  bearing on a current signal does not.

- Read `outstanding_signals` from the checkpoint and re-evaluate them against current logs, suppressions, work, and code history. Retain only signals that still require a retry or the next window's recurrence check. A completed window with no recurrence after the recorded repair removes that signal from the checkpoint.
- New evidence for an already tracked failure updates its outstanding state when it remains unresolved; it does not create a second bug for the same failure. Route amendments per `sdlc/policy/todo-creation-discipline`.

4. File every remaining error signal through the bug front door.
   - State the operation and the observed consequence the records support,
     distinguishing the operation's outcome from how that outcome is surfaced.
     An operation the records identify as attempted is stated as the report's
     subject, and one report carries one mechanism
     (`sdlc/policy/todo-creation-discipline`). Where several
     operations are identified, preserve a relationship only where the records
     establish it rather than merely display it: failures observed close
     together, or within one session, are correlated by that observation alone
     and the correlation is recorded as such, never asserted as a causal
     sequence (`general/principle/grounding`). Where an operator-initiated or
     otherwise deliberate action sits in the sequence, establish it before
     attributing anything downstream of it to a failure upstream.
     State the expected outcome with its supporting source: the current
     contract the operation contradicts, located through `telec docs index` and
     stated in the report with how the operation breaks it. Preserve an unknown operation or outcome
     explicitly; never infer one from an error signature. A signal whose
     expected outcome no current contract states is not a bug
     (`sdlc/policy/todo-creation-discipline`):
     do not file it or retain it in runner state; the session transcript remains the record of the observed operation and consequence.
     A
     reporting defect is stated as the discrepancy in reporting, without
     asserting that the underlying operation failed.
   - Submit the observed error summary and a representative log excerpt through
     `telec bugs report '<description>'`. Use `--project <owner>` when the
     defective system belongs to a different project than the scanned logs.
   - Follow the front door's pre-filing instructions and completion invocation.
     Its direct-fix question supplies no coding authority to a job.
   - Let the front door derive the slug. Record the returned bug slug and confirm
     creation from the result; an instruction card is not a created bug.
   - If filing fails, record the signal and error as outstanding, then continue
     with the remaining signals.

5. Prepare and submit the complete replacement checkpoint using the schema under Outputs.
   - A complete scan has successful collection, causal classification, and deduplication, with every eligible signal filed, excluded, matched to suppression, existing work, or in-flight work, or carried solely for the recurrence check in Step 3. Set `completed_until` to the window's end and `incomplete_scan` to `null`. Keep only the signals that still require that recurrence check.
   - A collection, lookup, classification, or filing failure keeps the prior `completed_until`, sets `incomplete_scan` to the attempted window's start/end, and retains the affected signals with their retry evidence. An outstanding filing keeps the scan incomplete.
   - Submit once through `telec jobs report <name> --success <true|false> --message '<summary>' --state-json '<replacement-state-object>'`. Use `true` for a complete scan and `false` for an incomplete scan. An empty successful collection is a complete scan. The JSON argument contains all checkpoint fields, including explicit `null` values and an empty signal array when applicable.

## Outputs

- A bug filed for each observed error that passes the causal gate and is neither suppressed
  nor already tracked.

- One latest outcome and checkpoint envelope at `STATE_DIR/runs/<project_slug>/<job_name>.json`, written by `telec jobs report`. The checkpoint occupies its `state` object and uses the schema below.
- Only the cursor, incomplete window, and unresolved retry evidence persist between runs. Resolved signals leave the checkpoint; session transcripts carry the completed dispositions (`sdlc/policy/todo-creation-discipline`).

### Checkpoint schema

The following schema belongs to this procedure. `telec jobs report` stores the
supplied object without interpreting these fields.

| Field                 | Shape                                                            | Meaning                                                                          |
| --------------------- | ---------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `completed_until`     | UTC RFC 3339 timestamp or `null`                                 | Exclusive end of the last completely processed scan window.                      |
| `incomplete_scan`     | Object with UTC RFC 3339 `start` and `end` timestamps, or `null` | Fixed window to retry when the previous scan was incomplete.                     |
| `outstanding_signals` | Array of signal objects                                          | Only unresolved retries or post-repair recurrence checks needed by the next run. |

Each outstanding signal has these fields:

| Field          | Shape                  | Meaning                                                                                            |
| -------------- | ---------------------- | -------------------------------------------------------------------------------------------------- |
| `summary`      | String                 | Observed operation and failure requiring re-evaluation.                                            |
| `last_seen_at` | UTC RFC 3339 timestamp | Latest occurrence supported by the saved evidence.                                                 |
| `evidence`     | String                 | Addressable log evidence and representative excerpt, with the established contract when available. |
| `retry_reason` | String                 | Failed lookup or filing, or the pending post-repair recurrence check.                              |

First-run defaults are:

```json
{
  "completed_until": null,
  "incomplete_scan": null,
  "outstanding_signals": []
}
```

Each submission replaces the whole checkpoint. Outcome summaries are supplied
through `--success` and `--message`. The scheduled job's declaration supplies its
name and project context.

## Recovery

- If logs cannot be collected, keep the saved `completed_until`, record the attempted window in `incomplete_scan`, retain unresolved evidence, and submit that replacement checkpoint with `--success false`.

- If suppression, active-work, or repository-history lookup fails, preserve the
  affected signals as outstanding and report failure. Resume deduplication on the
  next run. An unavailable history query never promotes a signal to filing: an
  unanswered "was this already repaired" is an outstanding signal, not a new one.
- If the available observations cannot falsify congestion or a computer restart for an error,
  record the causal-evidence gap and exclude that error from filing. Uncertainty never promotes
  an operationally explainable error into a bug report.

- A missing file or absent checkpoint uses the first-run defaults and declared schedule interval. A failed filing leaves the remaining signals eligible for processing; retain its evidence in `outstanding_signals` for re-evaluation before retrying.
- If a present checkpoint cannot be read or does not match the schema, stop the scan and report failure without `--state-json`. That outcome-only submission leaves the saved checkpoint unchanged. Record the checkpoint problem in the session transcript rather than guessing a cursor.
- If `telec jobs report` fails, record its failure in the session transcript and stop procedure execution. Without an accepted report, the run remains open until the runner marks it stalled after its reporting window. The reporting command owns durable writes; the procedure creates no substitute state or report file.

- Tool failures do not authorize repairing scripts, editing code, or bypassing
  permissions. Record them and close the run as failed.

## See Also

- ~/.teleclaude/docs/sdlc/policy/observability.md
- ~/.teleclaude/docs/sdlc/policy/todo-creation-discipline.md
- ~/.teleclaude/docs/general/policy/human-contract.md
