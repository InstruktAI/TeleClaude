---
delivered_by:
  - ci-results-as-events
description: A red required CI check on main or on a dependency update files one bug per failing job and step in the project's work, adds later failures to it, and records the check's recovery, all without an agent.
visibility: internal
---

# Failed Check Bugs — Spec

## What it is

A required check that fails on main or on a dependency update files its own
bug. The platform files it from the check's outcome
(`local/projects/teleclaude/spec/feature/integration/ci-run-outcomes`),
under the filing rule in `sdlc/policy/todo-creation-discipline` and the evidence
classification in `sdlc/concept/defect-evidence`. No agent observes, triages or
files it. The bug enters the project's work as an ordinary bug, and the bug lane
diagnoses which change or component is at fault and whether the check itself is
wrong.

**Business value:** a broken revision reaches the bug lane within one CI run and
carries its own evidence. Repeats of one failure stay in one bug instead of
piling up.

## Canonical fields

### What files

- A `red` outcome of a required check on main, or on a dependency-update pull
  request, files. Outcomes of other workflows or on other branches, and `green` or
  `none` outcomes, file nothing.
- Each failed job with its failed step is one failure, identified by its
  fingerprint: the check, the job and the step, as the filing rule fingerprints
  them. The branch is not part of the fingerprint, so the same failure on main and
  on a dependency update is one bug. Several failures in one run file or update
  one bug each.

### The filed bug

A failure whose fingerprint has no open bug files one bug in the project's work.
The bug states:

- the check, the job and the step that failed, and the fingerprint;
- the revision and branch that failed;
- the run's address;
- the commits since that branch's last `green` run of the same check;
- that the cause is not established.

An open bug is one that is neither delivered nor removed. A fingerprint whose
earlier bug was delivered or removed files a new bug.

### Repeats and recovery

- A failure whose fingerprint has an open bug adds an occurrence to that bug: the
  run's address, the revision, the branch and the commits since that branch's
  last `green` run. Nothing new is filed.
- A later `green` run of the same check on a branch for which the open bug holds
  a failure is recorded on that bug as the branch's recovery, with the run's
  address and revision. Recording a recovery leaves the bug open. Whether it is
  fixed, flaky or obsolete is decided in the bug lane.
- Each failure of one run completion is filed or added once, and each recovery
  is recorded once, however often the outcome is received.

### Use cases

#### UC-FCB1: An operator learns of a failed required check without watching CI

```gherkin
Given an operator's project declares a required check
And no open bug exists for a failure of that check
When the check fails on main
Then one bug is filed in the project's work naming the failed check, job and step
And it carries the run, the failed revision and the commits since the last passing run
```

#### UC-FCB2: A repeated failure joins the bug already open for it

```gherkin
Given a bug is open for a failure of a required check
When the same check fails at the same job and step again, on main or on a dependency update
Then that bug records the new occurrence
And no second bug is filed
```

#### UC-FCB3: A check that passes again is recorded as recovered on its bug

```gherkin
Given a bug is open for a failure of a required check on main
When that check later passes on main
Then the bug records the recovery with the passing run
And the bug remains open for the bug lane to settle
```

## Known caveats

- Commits since the last `green` run cover every delivery in a batched push. The
  filing names them all and attributes the failure to none.

## See Also

- docs/local/spec/feature/integration/ci-run-outcomes.md — the outcomes this filing reacts to.
- docs/local/spec/feature/workflow/todo-creation.md — the work's creation contract.
