---
description: Review a lifecycle build by slug against its prepared intent, plan, implementation, and shared review contract.
role: reviewer
parameters:
  - name: slug
    required: true
dispatch:
  agent: [codex, claude, gemini, deepseek]
  thinking_mode: med
---

# Review Build — Procedure

## Required reads

- @~/.teleclaude/docs/sdlc/procedure/lifecycle/review.md
- @~/.teleclaude/docs/sdlc/policy/preparation-artifact-quality.md

## Goal

Review the implementation dispatched for one slug against its approved intent,
prepared artifacts, and standards. The slug supplies the review context; the
shared review procedure supplies the review judgment.

## Preconditions

- The slug was supplied by the dispatching work orchestrator.
- The approved intent artifact resolves: `prd` for a `feature`; `input` for a
  `change` or `bug`; the implementation plan's _Intent & scope_ for a planned
  change with no input.
- `implementation-plan` exists for every kind.
- `architecture` is readable when present and not skipped.
- `quality-checklist` exists with Build and Review sections.
- The build phase completed for the slug.

## Steps

<!-- planned:role-scoped-cli-context -->

When this procedure is your session’s launch assignment, retrieve its focused tool
help with `telec -h --expand-role` before starting the assigned work. When reading
it inline, retain your current session’s tool context. Use `telec <command> -h`
for individual commands.
<!-- /planned:role-scoped-cli-context -->

### 1. Establish the slug's review context

Use the slug supplied by the dispatch. A build reviewer never selects work from
`telec todo list`.

Apply the artifact-discovery rule from
`sdlc/policy/preparation-artifact-quality`: list the slug's
artifacts, read `log` when present, and read every artifact relevant to the
review.

Read in full:

- The kind-resolved approved intent artifact. For a bug, also read
  `diagnosis`. Historical `requirements` artifacts remain readable records but
  carry no live intent fallback.

- `architecture` when present, plus the domain or design snippets it indexes.
- `implementation-plan`.
- `plan-review-findings`.
- `quality-checklist`.
- The relevant project README, generated agent instructions, and current
  project documentation through `telec docs`.

The intent artifact outranks the plan as scope authority. A behavioral delta
that the intent does not call for is a Critical scope finding even when the
approved plan contains it. For a bug, `input` sharpened by `diagnosis` is the
scope authority.

The plan's file placement, helper names, and decomposition anticipate the work
and do not bound it (`sdlc/policy/preparation-artifact-quality`). A difference
between them and the diff is not a finding by itself; a finding cites the
contract the difference violates and establishes the contradiction
(`sdlc/procedure/lifecycle/review`). The departures the builder recorded in
`log` are its stated reasons, and the review checks them independently against
the diff.

State what every required outcome promises before running a lane. Reading only
the diff is insufficient.

Reconstruct the required outcomes independently from the intent, contract
delta, applicable governing principles, and verified blast radius. Compare
that set with the plan and the diff; checking only the plan's listed tasks can
miss an escaped regression. Trace both directions: each required outcome to
the implementation that delivers it, and each material element of the diff to
authorized intent or a principle applied to verified substrate. An element
tracing to neither is invention and a finding. Handling of an unreachable
condition (`sdlc/concept/defect-evidence`) traces to neither unless the plan
carries it or `sdlc/policy/security-awareness` requires it on a path a party
without reach to the asset can drive input into. An outcome absent from the plan
is a preparation defect and triggers kickback; an outcome the diff fails to
deliver is a build finding.

Use merge-base to focus the implementation diff:

```bash
git diff $(git merge-base HEAD origin/main)..HEAD --name-only
git diff $(git merge-base HEAD origin/main)..HEAD
```

Orchestrator-managed state files are task context. Do not raise findings for
them unless the review scope explicitly includes planning or state edits.

### 2. Check build completeness

- Every implementation-plan task is delivered by a commit or explicitly
  deferred under the plan.
- Every deferred task is justified. A deferred task whose subject is a defect
  in the delivered change is not justified: the delivery is incomplete.
- Every ratchet candidate names the structural-ratchet condition that failed
  (`sdlc/policy/definition-of-done`); a qualifying deepening left undone is
  unjustified.
- An observation needs no justification. One whose subject lies inside the
  delivered change is judged as a defect of the delivery.

An undelivered task without a deferral, or an unjustified deferral, yields
`REQUEST CHANGES`.

### 3. Execute the shared review contract

Execute `sdlc/procedure/lifecycle/review` in full.

For this invocation:

- The target is the dispatched slug.
- The applicable contract is the approved intent and its success criteria.
- The scope lane runs.
- All catalog lanes run according to their trigger conditions.
- Builder entries in `quality-checklist` direct attention but never
  substitute for independent review of the diff.

### 4. Persist the build-review result

Write the complete findings to:

```bash
telec todo artifacts write {slug} review-findings "<content>"
```

Stamp the arithmetic verdict:

```bash
telec todo stamp {slug} --verdict approve|changes_requested --phase build_review
```

State the summary and verdict in your own turn output. Completing that turn is
what reaches the work orchestrator, which reads it there; you send it nothing.
The reviewer writes no other artifact and makes no source change.

## Outputs

- `review-findings` persisted on the dispatched slug.
- `build_review` verdict stamped on the dispatched slug.
- Summary and verdict stated in the reviewer session's own turn output, which
  the work orchestrator reads on that turn's completion.

### Report format

```text
REVIEW COMPLETE: {slug}

Requirement-Violations:
- <finding with citation>

Critical:
- <finding with citation>

Important:
- <finding with citation>

Verdict: APPROVE | REQUEST CHANGES
```

## Recovery

If the slug or a required prepared artifact cannot be resolved, report the
blocker and stop. Never select another todo as a substitute.
