---
description: Review discrete commits already on main by SHA, without a worktree or the todo lifecycle.
role: commit-reviewer
parameters:
  - name: shas
    required: true
dispatch:
  agent: [codex, claude, gemini, deepseek]
  thinking_mode: slow
---

# Review Commits — Procedure

## Required reads

- @~/.teleclaude/docs/sdlc/procedure/lifecycle/review.md
- @~/.teleclaude/docs/sdlc/policy/todo-creation-discipline.md

## Goal

Review a discrete set of commits already landed on main, identified by SHA,
without requiring a worktree or the todo lifecycle. The SHA list supplies the
review context; the shared review procedure supplies the review judgment.

## Preconditions

- `$ARGUMENTS` is a comma-separated discrete list of commit hashes, not a
  range.
- Each SHA names exactly one commit. Commits authored by others may sit between
  the named SHAs and remain out of scope.

## Steps

<!-- @include: docs/snippets/step-role-read.md -->

### 1. Validate the discrete SHA list

Parse `$ARGUMENTS` as a comma-separated list. Confirm every SHA exists with
`git cat-file -t`. Gaps between named commits are valid.

### 2. Inspect each named commit in isolation

For each SHA, inspect its authored message, complete diff, and file list:

```bash
git show <sha>
git show --stat <sha>
```

Read full changed-file context at the named commit with
`git show <sha>:<path>`. Do not use neighboring commit state.

Mechanically attached records are outside the authored review target.

Never compute a range diff or range log. Range forms silently include commits
the reviewer was not given. Named commits may still be checked together — how
they compose, or whether a named remediation repairs an earlier named change —
using the named snapshots as evidence while each commit keeps its own
attribution.

### 3. Execute the shared review contract

Execute `sdlc/procedure/lifecycle/review` in full.

For this invocation:

- The target is the discrete SHA list.
- The applicable contracts are the governing policies, principles, specs, and
  resulting behavior touched by the named commits.
- Establish the intent basis and governing contracts available for the named
  changes. A commit message states the author's claims; it does not itself
  authorize scope. Where an authoritative intent basis is available, apply scope
  verification against it within the named review target. Otherwise state that
  limitation and assess the resulting change against its governing contracts. A
  material authority gap that prevents judgment is a blocker under
  `sdlc/procedure/lifecycle/review`, not permission inferred from the message.
- The conversation that produced a named commit is part of its intent basis
  (`general/policy/human-contract`). A commit made in an agent session records
  that session in its `Session:` trailer; read its transcript with
  `telec history show <session_id>`, or with
  `telec sessions tail <session_id> --since <time>` reaching back before the
  change was shaped, since a plain tail returns only the latest turn. Intent
  forms in the exchange: agents propose and do the work, and the human steers,
  releases and corrects. Read the part of the conversation that shaped the
  change in order, and take its intent from what was proposed and how the human
  responded, through to any later correction. Form that reading before weighing
  the author's account; the additional context and the authored message are
  claims about the conversation and are checked against it. A user-role entry in
  these reads can carry a peer's relayed text, so attribute words to the human
  only where the conversation establishes it. A commit without a `Session:`
  trailer, such as a human's terminal commit, keeps the intent basis above.
  A transcript that cannot be read is handled as
  `sdlc/procedure/lifecycle/review` Step 0 states; its absence alone is not a
  material authority gap.
- Check material claims in the authored message against the diff and resulting
  behavior. Classify any contradiction under the governing contract; message
  consistency does not establish intent authority.
- A documentation change to what agents are directed to do arrives with its
  intent, in your additional context or in the message that handed you the
  series (`general/policy/documentation-discipline`). Hold the changed text to that
  intent for the reader role it names: each intended behavior is produced for
  that reader, nothing intended is lost or distorted, nothing beyond it is
  added, and the intent itself holds against the governing contracts. Such a
  change dispatched without its intent is a material authority gap.

- The authoring caller owns continuation and recovery for this review; the
  reviewer retains verdict authority. Apply the shared convergence contract
  without introducing a lifecycle phase.

- Every other lane runs according to the shared catalog's trigger conditions,
  against only the named changes.
- The doc-hygiene lane runs whenever a named commit changes a doc snippet.
- Run the doc-first paradigm lane when its trigger in
  `sdlc/policy/definition-of-done-lanes` applies.
- When a named commit changes `docs/third-party/**`, load
  `general/spec/third-party-docs` and verify that each root belongs to one
  upstream party, the selected scope is justified, the content is factual
  upstream documentation rather than local architecture or comparison, and
  authoritative sources and explicit gaps are present where applicable.

For the tests lane, apply every `TQ-*` predicate triggered by the named diffs
and record evidence or a reasoned `N/A`.

### 4. Return the commit-review result

Print the complete report the shared review procedure requires — every executed
lane's section and, when no Important-or-higher finding remains, its clean-pass

evidence — with the verdict, to the caller. Then stamp the verdict on exactly
the named SHAs:

```bash
telec repo stamp <sha1>,<sha2>,... --verdict approve|request_changes
```

The stamp resolves its todo, if any, from the session that started this
review. Do not select a todo or write a todo artifact.

Use comma-separated commit notation in the target line, never range notation:

```text
REVIEW COMPLETE: commits <sha1[:8]>,<sha2[:8]>,...,<shaN[:8]>
```

### 5. Remediation pass

A follow-up addressing this review continues its existing findings ledger under
`sdlc/procedure/lifecycle/review`. Identify the prior report and target, read the
producer's dispositions and evidence, inspect each named remediation commit in
full, and independently determine which findings are resolved, invalid or still
open. An evidence-only rejection may require no new commit.

Apply the shared re-review boundaries to new findings. Emit a complete report
identifying the original target and any remediation SHAs, with current lane
assessments and a verdict over all unresolved findings. Approval of a
remediation commit alone does not close the original review.

Keep the discrete-SHA boundary: intervening commits are not additional review
targets. If establishing closure requires reviewing another commit, identify the
missing SHA rather than silently expanding the target. A request naming
unrelated new work is a separately scoped review, not part of this remediation
cycle, whichever session receives it.

An acknowledgement without a verdict line is never a review outcome; the caller
never infers one.

Stamp the remediation verdict on every named SHA the report covers, original
and remediation alike.

## Outputs

- Review findings printed to the caller.
- Verdict printed to the caller.

- A commit-review stamp over the named SHAs; no todo artifact.

## Recovery

Already-merged code receives no leniency:

- A pre-existing pattern does not excuse a cited violation in the resulting
  state of a touched file.
- Merge state does not lower finding severity.
- A finding against a commit outside the supplied SHA list is out of scope and
  is dropped.

If a supplied SHA cannot be resolved, report the blocker and stop. Never expand
the review to nearby commits.
