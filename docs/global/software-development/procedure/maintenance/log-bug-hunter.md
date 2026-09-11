---
description: 'Proactive log-scanning job that discovers daemon errors and files a minimal bug report for each unsuppressed signal.'
visibility: 'public'
---

# Log Bug Hunter — Procedure

## Goal

Scan the current project's logs, deduplicate error signals, and file the remaining
observed failures through `telec bugs report`. The bug lifecycle owns diagnosis
and implementation.

## Preconditions

- The runner started this session in the target project with this procedure's
  snippet ID as the job identity.
- The project's log name and the job's schedule are available from its configuration.
- `instrukt-ai-logs`, `telec bugs suppressions`, `telec bugs list`,
  `telec todo list`, and `telec bugs report` are available.
- The run history is the Markdown reports in the directory named under Outputs.

## Steps

1. Establish the scan window for this project.
   - Read the latest report belonging to this project. Start at its completed
     scan's end; if it records an incomplete scan, resume from that scan's start.
   - With no usable prior report, cover one schedule interval from the job's
     declaration. Record the actual start and end timestamps.
   - Collect that window with
     `instrukt-ai-logs {project_slug} --since <window> --exclude 'logger=(git-wrapper|teleclaude\.git\.exec)'`.
     A successful empty result is a clean scan. A failed collection is an
     incomplete scan, reported under Recovery.

2. Read the logs and group related errors, exceptions, tracebacks, and repeated
   warnings into distinct signals. Ignore informational and debug output.
   Use the observed messages and context; do not investigate the codebase to
   establish a diagnosis.

3. Deduplicate each signal.
   - Read `telec bugs suppressions` for the project. Match only active entries,
     using each entry's declared substring or regex semantics. Record matches
     with their suppression IDs. Skip an invalid regex and record that error.
   - Read `telec bugs list` and `telec todo list`. Record a matching active
     bug or todo by its slug instead of filing a duplicate.
   - Read the latest three reports for this project for prior dispositions and
     context. A previous failed filing or an unresolved signal remains outstanding;
     merely mentioning a signal in a report does not make it handled.
   - New evidence for an already tracked failure belongs with that finding in
     this run's report; it does not create a second bug for the same failure.

4. File every remaining signal through the bug front door.
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
   Mark the scan complete only after log collection and deduplication succeeded
   and every signal has been filed or matched to an active suppression or
   existing work. An outstanding filing keeps the scan incomplete.
   Return the outcome to the job brief's structured close-out step.

## Outputs

- A bug filed for each observed error that is neither suppressed nor already tracked.
- A Markdown report named by the run timestamp in the job's run directory:
  `~/.teleclaude/jobs/{project_slug}/{job_id}/runs/`.

Create the directory when needed. Each report carries:

- **Summary:** project, scan start and end, complete or incomplete, and outcome.
- **Findings:** each signal's observed evidence and disposition — filed bug slug,
  existing work slug, suppression ID, or outstanding filing.
- **Errors:** collection, deduplication, or filing failures; use "None" when absent.

The report is the scan history consumed by the next run. The structured outcome
submitted by the job brief records whether this run completed successfully.

## Recovery

- If logs cannot be collected, record the failed collection and an incomplete
  scan. Report failure; do not describe unavailable logs as a clean run.
- If suppression or active-work lookup fails, preserve the affected signals as
  outstanding and report failure. Resume deduplication on the next run.
- A missing report history is a first scan, not a failed lookup; use the declared
  schedule interval and current suppression and work records.
- A failed filing does not block attempts for other signals. Carry its evidence
  in the report so the next run can retry after deduplication.
- Tool failures do not authorize repairing scripts, editing code, or bypassing
  permissions. Record them and close the run as failed.

## See Also

- ~/.teleclaude/docs/software-development/policy/todo-creation-discipline.md
- ~/.teleclaude/docs/general/policy/human-contract.md
