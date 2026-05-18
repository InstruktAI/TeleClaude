---
description: 'Drift analysis phase. Classify each pending prepare-artifact drift as cosmetic or substantive and stamp the verdict so the lifecycle can continue or re-derive the affected layer.'
domain: 'software-development'
id: 'software-development/procedure/lifecycle/prepare/drift-analyze'
scope: 'domain'
type: 'procedure'
visibility: 'public'
---

# Drift Analyze — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/regression-zero-tolerance.md

## Goal

Classify each pending codebase drift recorded for a prepared artifact. Stamp
`cosmetic` when the artifact remains valid despite the changed code. Stamp
`substantive` when the artifact must be re-derived to match current reality.

## Preconditions

- The prepare state machine reported one or more artifacts with
  `drift.<artifact>` = `pending` and recommended this worker.
- The slug is active and not delivered.

## Steps

### 1. Identify pending artifacts

Read the prepare state machine output (or `telec todo show {slug}`) to
enumerate which artifacts are pending drift review.

### 2. For each pending artifact

- Read the artifact: `telec todo artifacts read {slug} <artifact>`.
- Read the recorded `codebase_sha_at_write` and `referenced_paths` from
  state.
- Inspect the diff between `codebase_sha_at_write` and the current HEAD,
  scoped to the artifact's referenced paths. Use `git log` and
  `git diff <baseline>..HEAD -- <referenced-paths>` directly.
- Judge whether the changes invalidate the artifact's claims, success
  criteria, or implementation directions:
  - **`cosmetic`** — the artifact's intent and claims still hold. Examples:
    rename/refactor that preserves behavior; constants extraction;
    formatting; doc edits unrelated to the artifact's grounding.
  - **`substantive`** — the artifact's claims are now wrong or its
    referenced surfaces no longer exist as described. The artifact's owning
    layer must re-derive.

### 3. Stamp the verdict

For each pending artifact:

```bash
telec todo stamp {slug} --drift-reviewed <artifact> cosmetic <reason>
# or
telec todo stamp {slug} --drift-reviewed <artifact> substantive <reason>
```

Reason text names what changed in the diff and why it does or does not
invalidate the artifact.

### 4. Go idle

After every pending artifact has a stamp, end the worker turn. The
dispatching session re-enters the state machine and acts on the new state.

## Outputs

- One `--drift-reviewed <artifact> cosmetic|substantive <reason>` stamp per
  pending artifact.

## Discipline

Classify drift only. Do not rewrite prepare artifacts, do not approve gates,
do not start build work. The artifact's owning phase skill (intake,
architecture, specs, plan) re-derives substantive drift when the dispatching
session re-enters the state machine.

A `cosmetic` verdict must be grounded in the actual diff, not assumed. If
the diff cannot be cleanly classified, stamp `substantive` and let the
owning layer re-derive.

## Recovery

- If the referenced paths cannot be read (deleted, renamed without rename
  detection, etc.), stamp `substantive` and explain in the reason — the
  owning layer must re-derive against the new reality.
- If the baseline SHA cannot be resolved (history rewrite, missing object),
  stamp `substantive` — provenance cannot be verified.

## See Also

- ~/.teleclaude/docs/software-development/policy/regression-zero-tolerance.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/overview.md
