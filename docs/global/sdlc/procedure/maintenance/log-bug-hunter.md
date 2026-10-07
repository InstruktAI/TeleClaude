---
description: 'Proactive log-scanning job that discovers daemon errors and files a minimal bug report for each unsuppressed signal.'
visibility: 'public'
---

# Log Bug Hunter — Procedure

## Required reads

- @~/.teleclaude/docs/sdlc/concept/defect-evidence.md
- @~/.teleclaude/docs/sdlc/policy/todo-creation-discipline.md

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
- The run history is the Markdown reports in the directory named under Outputs.

## Steps

1. Establish the scan window for this project.
   - Read the latest report belonging to this project. Start at its completed
     scan's end; if it records an incomplete scan, resume from that scan's start.
   - With no usable prior report, cover one schedule interval from the job's
     declaration. Record the actual start and end timestamps.
   - Collect that window with
     `instrukt-ai-logs {project_slug} --since <window> --exclude 'logger=git-wrapper'`.
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
   - When congestion or a computer restart explains the error, exclude it. When the available
     observations cannot rule out either cause, exclude it as causally inconclusive. Record the
     exclusion in the run report; never create a bug to obtain the missing causal evidence.

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
   - Read the latest three reports for this project for prior dispositions and
     context. A previous failed filing or an unresolved signal remains outstanding;
     merely mentioning a signal in a report does not make it handled.
   - New evidence for an already tracked failure belongs with that finding in
     this run's report; it does not create a second bug for the same failure.
     Route it per the amendment rules in
     `sdlc/policy/todo-creation-discipline`.

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
     State an expected outcome only with its supporting source.
     Preserve an unknown operation, outcome, or expectation explicitly; never
     infer one from an error signature. A reporting defect is stated as the
     discrepancy in reporting, without asserting that the underlying operation
     failed.
   - Submit the observed error summary and a representative log excerpt through
     `telec bugs report '<description>'`. Use `--project <owner>` when the
     defective system belongs to a different project than the scanned logs.
   - Follow the front door's pre-filing instructions and completion invocation.
     Its direct-fix question supplies no coding authority to a job.
   - Let the front door derive the slug. Record the returned bug slug and confirm
     creation from the result; an instruction card is not a created bug.
   - If filing fails, record the signal and error as outstanding, then continue
     with the remaining signals.

5. Write the run report under Outputs, including a clean or failed scan.
   Mark the scan complete only after log collection, causal classification, and
   deduplication succeeded and every eligible error signal has been filed, excluded,
   carried for recurrence, or matched to an active suppression, existing work, or
   in-flight work. An outstanding filing keeps the scan incomplete.
   Return the outcome to the job brief's structured close-out step.

## Outputs

- A bug filed for each observed error that passes the causal gate and is neither suppressed
  nor already tracked.
- A Markdown report named by the run timestamp in the job's run directory under
  `JOBS_DIR`, keyed by the runner's project-qualified `<project>:<name>` identity.
  Use the same run directory that `telec jobs report <name>` writes to.

Create the directory when needed. Each report carries:

- **Summary:** project, scan start and end, complete or incomplete, and outcome.
- **Findings:** each eligible error signal's observed evidence and disposition — filed bug
  slug, existing work slug, in-flight slug that owns the mechanism, suppression ID, exclusion
  cause, a signal carried for recurrence after a repair landed, or outstanding filing. Warning
  records do not appear as findings. A carried signal names the commit that repaired its path,
  so the next run can file it without repeating this run's history query.
- **Errors:** collection, deduplication, or filing failures; use "None" when absent.

The report is the scan history consumed by the next run. The structured outcome
submitted by the job brief records whether this run completed successfully.

## Recovery

- If logs cannot be collected, record the failed collection and an incomplete
  scan. Report failure; do not describe unavailable logs as a clean run.
- If suppression, active-work, or repository-history lookup fails, preserve the
  affected signals as outstanding and report failure. Resume deduplication on the
  next run. An unavailable history query never promotes a signal to filing: an
  unanswered "was this already repaired" is an outstanding signal, not a new one.
- If the available observations cannot falsify congestion or a computer restart for an error,
  record the causal-evidence gap and exclude that error from filing. Uncertainty never promotes
  an operationally explainable error into a bug report.
- A missing report history is a first scan, not a failed lookup; use the declared
  schedule interval and current suppression and work records.
- A failed filing does not block attempts for other signals. Carry its evidence
  in the report so the next run can retry after deduplication.
- Tool failures do not authorize repairing scripts, editing code, or bypassing
  permissions. Record them and close the run as failed.

## See Also

- ~/.teleclaude/docs/sdlc/policy/observability.md
- ~/.teleclaude/docs/sdlc/policy/todo-creation-discipline.md
- ~/.teleclaude/docs/general/policy/human-contract.md
