---
description: 'Judge what a build left outside its plan: decide each deferred item, file only the observations that meet the filing standard, and mark deferrals as processed.'
visibility: 'public'
role: deferrer
parameters:
  - name: slug
    required: true
dispatch:
  agent: [claude, codex, gemini, deepseek]
  thinking_mode: slow
---

# Deferrals — Procedure

## Required reads

- @~/.teleclaude/docs/sdlc/concept/defect-evidence.md
- @~/.teleclaude/docs/sdlc/policy/todo-creation-discipline.md

## Goal

- Decide every entry a build recorded outside its plan, create or file only
  what the creation policy admits, and record completion.

## Preconditions

- `telec todo artifacts read {slug} deferrals` exists.
- A deferrals artifact exists and has not been processed.

## Steps

When this procedure is your session’s launch assignment, retrieve its focused tool
help with `telec -h --expand-role` before starting the assigned work. When reading
it inline, retain your current session’s tool context. Use `telec <command> -h`
for individual commands.

1. Read `telec todo artifacts read {slug} deferrals`. Each entry has a heading
   naming it and these fields:
   - `Kind` — `deferred-task` (a plan task the build did not deliver),
     `ratchet-candidate` (a structural deepening the build did not perform), or
     `observation` (a possible defect noticed outside the build's tasks).
   - `What` — the task, the deepening, or what was seen and where.
   - `Basis` — why a task or deepening stayed outside this build, or, for an
     observation, how it was noticed.

   An entry proposes no outcome; deciding it is this procedure's work.

2. Decide each entry by its content; its `Kind` label directs attention but
   does not decide. An entry whose content claims a defect, or proposes a
   defense against one, is decided as an observation under any label.
   - **A deferred task or ratchet candidate** — apply
     `sdlc/policy/todo-creation-discipline`. When it warrants its own work,
     create a new, independent todo with
     `telec todo create <new_slug> --kind <kind>` — never `--group {slug}`.
     Grouping is reserved for prepare-phase scope-splitting (a planner
     decomposing an oversized plan into children); it strips the parent's
     lifecycle state and must never be used to attach a deferred follow-up to a
     todo that is already mid-flight or finalizing. Add `--after {slug}` only
     when the deferred item has a genuine technical dependency on this todo;
     otherwise it stands on its own. Otherwise close the entry.
   - **An observation** — the builder's notice is a lead, not evidence. File
     it only when you can cite the occurrence or dangerous path the policy
     requires: a defect through `telec bugs report`, the surface that asks for
     that evidence, and a defense as the work it is, carrying the same
     evidence. Otherwise close the entry.
3. Record each entry's disposition — the created or filed slug, or why it was
   closed — in the todo's `log`.
4. Stamp processing complete:
   - `telec todo stamp {slug} --deferrals-processed`
5. Commit all changes and report a summary.

## Outputs

- Every entry decided, with its disposition in `log`.
- New todos and bug filings only where the creation policy admits them.
- Deferrals stamped as processed.

## Recovery

- If deferrals file is missing, stop and report; do not mark processed.
- An entry that proposes an outcome or lacks a `Kind` is decided by its content
  under step 2; the proposal carries no weight.

## Discipline

Every todo you create or file stands on evidence you grounded yourself: for a defect, the occurrence or dangerous path you cite. An entry's words are where your search starts; an entry you cannot ground closes with its reason in `log`.
