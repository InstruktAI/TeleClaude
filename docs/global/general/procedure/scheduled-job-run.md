---
description: What a scheduled job's session owes beyond its procedure — report the
  run's outcome once through the job report, then end itself.
---

# Scheduled Job Run — Procedure

## Goal

Close a scheduled job's run with one structured outcome so the runner can
correlate it to the open run, then end the session that ran it.

## Preconditions

- The session was started by the scheduled-job runner for a declared job; the
  brief names the job by its declared name and the procedure the job executes.
- The procedure's own outputs and recovery steps govern the work; this
  procedure governs only the close-out.

## Steps

1. Do the work the job's procedure assigns, following that procedure and its
   required reads as the complete instruction set.
2. Close the run with one
   `telec jobs report <job-name> --success <true|false> --message '<summary>' [--items-processed <n>] [--error '<error>' ...] [--state-json '<object>']`
   invocation. Report success only when the assigned work completed; an empty
   successful run also completes. Record a failed procedure load or execution
   as failure. The optional object follows the procedure's own checkpoint
   schema (`local/projects/teleclaude/spec/feature/agent_runtime/agent-job-reporting`).
3. End this session with `telec sessions end self` once the report is
   accepted.

## Outputs

- One accepted job report correlated to the open run.
- A closed session.

## Recovery

- If `telec jobs report` fails, record its failure in the session transcript
  and stop; the run stays open until the runner marks it stalled after its
  reporting window. The reporting command owns durable writes; create no
  substitute state or report file.
- A tool failure authorizes no code repair, script edit or permission bypass:
  record it and close the run as failed.

## Discipline

A job's session carries whatever role its procedure declares; that role
supplies no authority to edit or commit code the procedure does not assign.
Report once, then end: a job that lingers after its report holds a session the
runner has already accounted for.
