---
description: Every registered repository on every computer converges to the documentation
  layout — docs/local and agents/local, qualified identities — through one verified
  commit in its own repository, or reports why it cannot.
visibility: internal
---

# Documentation Layout Convergence — Spec

## Required reads

- @docs/local/spec/domain/context.md

## What it is

Documentation layout convergence brings every registered repository to the
documentation layout the context domain reads: local documentation under
`docs/local/`, local agent artifacts under `agents/local/`, and every snippet
reference in the qualified identity form, a home's local identities carrying the
`local/` prefix (`general/spec/snippet-authoring-schema`). Nothing reads the
earlier layout or the earlier identity forms, so a repository that has not
converged is invisible to indexing, validation, and selection until it does.

Convergence is a documentation-owned maintenance operation. It walks the
project registry, and for each available root it either finds the root current,
converges it with one commit in that root's own repository, or leaves it
unchanged and reports why. A convergence commit is always attributable: a run
with no attributable commit party — no agent session and no terminal login —
changes no root and defers every root that would converge. The checkout is its
own completion record: a root with neither `docs/project` nor `agents/project`,
whose tracked Markdown names no project-local identity without its `local/`
prefix, is current, so every run is idempotent and a convergence that arrived by
pull is recognized without bookkeeping. A root whose recorded tree still tracks a retired
directory that is gone from the checkout is an interrupted migration: it is
reported blocked, never current.

<!-- planned:convergence-overlap-and-failure-reporting -->

One run at a time converges a repository on a computer. A run that reaches a
repository another run is converging says it is waiting for that run, waits,
and then reads the repository as it stands, so overlapping runs never act on
one repository together.

<!-- /planned:convergence-overlap-and-failure-reporting -->

A convergence consists of:

- **The move.** `docs/project` becomes `docs/local` and `agents/project` becomes
  `agents/local`.
- **The reference rewrite.** Tracked text is rewritten at the identifier level
  only: paths into the old folders become paths into the new ones; the
  repository's own unqualified local identities become `local/projects/<slug>/…`
  with the slug the repository declares; person and company identities become
  `people/<slug>/…` and `companies/<slug>/…`; identities prefixed with a
  registered project's slug become `local/projects/<slug>/…`; and every
  project-local identity written as `projects/<slug>/…` — a registered project's
  slug, or the `<slug>`, `{slug}`, and `{project}` placeholders — gains the
  `local/` prefix wherever it stands, the published half included, because that
  form names a local snippet in every repository. Changelogs and generated files
  are never rewritten; a decision record keeps its body, and only the paths in
  its See Also list follow the move. Unqualified local identities in the
  repository's published half (`docs/global`) keep their form; their
  occurrences are reported to the owner, who decides whether each mention means
  that repository or the project at hand.
- **The commit.** One commit in the root's repository through the sealed commit
  path, carrying exactly the moved and rewritten paths. A root already on the
  converged layout whose only change is the `local/` prefix converges the same
  way, with a commit carrying only the rewritten paths.

<!-- planned-change:convergence-overlap-and-failure-reporting -->

Convergence runs on every computer: as a post-merge maintenance action on
computers that follow the branch, and from both install paths, which include
tag deployments. Where such a run has no attributable party, the roots it
defers converge on that computer's next attributable run. From an install or a
tag deployment, a non-zero result is printed as a warning and the install or
deployment still completes: no deferred or blocked repository fails a platform
upgrade. The post-merge maintenance action keeps its non-zero result.

<!-- change:convergence-overlap-and-failure-reporting -->

Convergence runs on every computer: as a post-merge maintenance action on
computers that follow the branch, and from both install paths, which include
tag deployments. Where such a run has no attributable party, the roots it
defers converge on that computer's next attributable run. A run's result tells
three cases apart: every root settled; some root blocked or deferred and none
failed; and some root failed, restored after a refused commit, or in restore
conflict. From an install or a tag deployment, a blocked or deferred result is
printed as a warning and the install or deployment still completes: no
repository that convergence correctly leaves for its owner or for a later
attributable run fails a platform upgrade. A failed result is printed as a
failure, and the install does not report completion and exits non-zero. The
post-merge maintenance action keeps its non-zero result in both cases.

<!-- /planned-change:convergence-overlap-and-failure-reporting -->

## Canonical fields

### Use cases

#### UC-DLC1: A registered repository on the earlier layout converges in one commit

```gherkin
Given a registered repository that carries docs/project or agents/project
And its declaration names its project slug
And every path the move and the reference rewrite touch is clean
And its upstream does not already carry the converged layout
When layout convergence runs
Then docs/project is moved to docs/local and agents/project to agents/local
And its tracked references are rewritten to the new paths and to qualified identities
And one commit in that repository, made through the sealed commit path, carries exactly the moved and rewritten paths
And the root is reported as migrated and committed
```

#### UC-DLC2: A repository on the converged layout is current

```gherkin
Given a registered repository with neither docs/project nor agents/project
And whose tracked Markdown names every project-local identity with its local/ prefix
When layout convergence runs
Then nothing in that repository changes
And the root is reported as current
And a second run over a repository converged by UC-DLC1 or UC-DLC13 reports it current
```

#### UC-DLC3: A clone whose upstream already converged is not migrated again

```gherkin
Given a registered repository still on the earlier layout
And its upstream, fetched within the run's bound, carries docs/local and no docs/project
When layout convergence runs
Then nothing in that repository changes and no commit is made
And the root is reported as needing a pull
```

#### UC-DLC4: A dirty touched path blocks that root

```gherkin
Given a registered repository on the earlier layout
And a path the move or the reference rewrite would touch is modified, or an untracked file stands in its way
When layout convergence runs
Then the repository is left unchanged
And the root is reported as blocked by a dirty path, naming it
And other roots in the run still converge
```

#### UC-DLC5: An undeclared project slug blocks that root

```gherkin
Given a registered repository on the earlier layout whose declaration yields no project slug
When layout convergence runs
Then the repository is left unchanged
And the root is reported as blocked by an undeclared slug
And no identity is derived from the directory name
```

#### UC-DLC6: Both layouts present block that root

```gherkin
Given a registered repository that carries docs/local beside docs/project, or agents/local beside agents/project
When layout convergence runs
Then the repository is left unchanged
And the root is reported as blocked by both layouts being present
```

<!-- planned-change:convergence-overlap-and-failure-reporting -->

#### UC-DLC8: A refused commit or a failed write reverses only convergence's own changes

```gherkin
Given a registered repository that UC-DLC1 would converge
And the sealed commit refuses the convergence commit, or a move, write or staging step fails after convergence began changing the repository
When layout convergence runs
Then convergence reverses only its own changes: each rewritten file whose bytes still equal what convergence wrote gets its original bytes back, each moved file whose bytes are still the ones convergence left returns to its original path, and each touched path whose index entry still equals one convergence observed returns to the committed entry
And a file whose bytes changed since convergence left them, a file convergence did not move, a moved file whose original path is occupied again, or a touched path whose index entry changed, is left exactly where and as found and named there
And the root is reported as a restore conflict when any such path exists, and otherwise as restored after a refused commit or as failed after a failed write, with the repository's files and index equal to their state before the run
```

<!-- change:convergence-overlap-and-failure-reporting -->

#### UC-DLC8: A refused commit or a failed write reverses only convergence's own changes

```gherkin
Given a registered repository that UC-DLC1 would converge
And the sealed commit refuses the convergence commit, or a move, write or staging step fails after convergence began changing the repository
When layout convergence runs
Then convergence reverses only the changes it made: each rewritten file whose bytes still equal what convergence wrote gets its original bytes back, each file convergence moved whose bytes are still the ones convergence left returns to its original path, and each path convergence staged whose index entry still equals what convergence staged returns to the committed entry
And a path convergence neither moved, wrote nor staged is neither restored, recreated nor named, so a directory move that did not happen leaves that directory and its counterpart as found
And a file whose bytes changed since convergence left them, a file another writer placed in a directory convergence moved, a moved file whose original path is occupied again, or a path convergence changed whose index entry changed since, is left exactly where and as found and named there
And the root is reported as a restore conflict when any such path exists, and otherwise as restored after a refused commit or as failed after a failed write, with every path convergence changed back in its state before the run
```

<!-- /planned-change:convergence-overlap-and-failure-reporting -->

#### UC-DLC9: Published-half mentions and records are reported, not guessed

```gherkin
Given a registered repository converged by UC-DLC1
And its docs/global snippets mention unqualified local identities
When layout convergence completes for that root
Then those docs/global mentions are unchanged
And the root's report lists them for the repository's owner
And changelogs, generated files, and decision-record bodies are unchanged
```

<!-- planned-change:convergence-overlap-and-failure-reporting -->

#### UC-DLC10: Every computer converges, tag deployments included

```gherkin
Given a computer that follows the branch and pulls a merge changing the layout owner
Or a computer that installs or deploys a tagged release
When the post-merge maintenance or the install completes
Then layout convergence has run over that computer's registered repositories
And where that run had no attributable party, it deferred the roots that would converge (UC-DLC12)
And the next attributable run on that computer converges them
And from an install or a tag deployment the run's report is printed and a non-zero result is a warning, while the install or deployment still completes
And from the post-merge maintenance action a non-zero result stays that action's result
```

#### UC-DLC11: The run reports every root and fails loudly on blocks

```gherkin
Given a layout convergence run over the project registry
When the run completes
Then it reports one outcome line per registered root and one run line
And a registered root that is absent on this computer is reported as unavailable and skipped
And linked worktrees of a converged root are listed in its report
And the run exits non-zero when any root is blocked, deferred, restored after a refused commit, or in restore conflict
```

<!-- change:convergence-overlap-and-failure-reporting -->

#### UC-DLC10: Every computer converges, tag deployments included

```gherkin
Given a computer that follows the branch and pulls a merge changing the layout owner
Or a computer that installs or deploys a tagged release
When the post-merge maintenance or the install completes
Then layout convergence has run over that computer's registered repositories
And where that run had no attributable party, it deferred the roots that would converge (UC-DLC12)
And the next attributable run on that computer converges them
And from an install or a tag deployment the run's report is printed, and a blocked or deferred result is a warning while the install or deployment still completes
And from an install a failed result is printed as a failure, and the install does not report completion and exits non-zero
And from the post-merge maintenance action a non-zero result stays that action's result
```

#### UC-DLC11: The run reports every root and tells failures from blocks

```gherkin
Given a layout convergence run over the project registry
When the run completes
Then it reports one outcome line per registered root and one run line
And a registered root that is absent on this computer is reported as unavailable and skipped
And linked worktrees of a converged root are listed in its report
And the run exits non-zero when any root is blocked, deferred, failed, restored after a refused commit, or in restore conflict
And its run line and its exit status tell a run with a failed, restored or conflicted root apart from a run whose only unsettled roots are blocked or deferred
```

<!-- /planned-change:convergence-overlap-and-failure-reporting -->

#### UC-DLC12: A run without an attributable party changes nothing and defers

```gherkin
Given a layout convergence run with no attributable commit party — no agent session and no terminal login, as in a deploy pull or a tag install
When the run walks the project registry
Then no root is moved, rewritten, or committed
And each root that would converge is reported as deferred for lack of an attributable party
And the report names the command that re-runs convergence
And current roots and roots needing a pull are still reported as such
```

#### UC-DLC13: A repository naming project-local identities without the local prefix converges in one commit

```gherkin
Given a registered repository with neither docs/project nor agents/project
And its tracked Markdown, in either half, names a project-local identity as projects/<slug>/… with a registered project's slug or a <slug>, {slug} or {project} placeholder
And every path the rewrite touches is clean
When layout convergence runs with an attributable party
Then each such identity gains the local/ prefix
And changelogs, generated files, and decision-record bodies are unchanged
And one commit in that repository, made through the sealed commit path, carries exactly the rewritten paths
And the root is reported as migrated and committed
```

<!-- planned:convergence-overlap-and-failure-reporting -->

#### UC-DLC14: Overlapping runs over one repository take turns

```gherkin
Given a layout convergence run is converging a registered repository on a computer
When a second layout convergence run on that computer reaches the same repository, from post-merge maintenance or from an install
Then the second run reports that it is waiting for the other convergence of that repository before it waits
And it neither assesses, fetches nor changes that repository until the first run has finished with it
And it then reports the repository as it stands, as current when the first run converged it
And no change the first run made is reversed or named by the second run
```

#### UC-DLC15: A run from a slug worktree reports other checkouts' repositories without failing

```gherkin
Given a layout convergence run whose code is loaded from a slug worktree
When it reaches a registered repository other than that worktree's own checkout
Then the root is reported as belonging to another checkout
And that root makes the run's result neither blocked, deferred nor failed
```

<!-- /planned:convergence-overlap-and-failure-reporting -->

### Cross-context references

- **config** — the project registry's roots and each repository's declared
  project slug. Declarations only; convergence registers nothing.
- **commit** — the sealed commit path is the only way convergence commits in
  another repository; its refusal is final for that run.
- **identity** — whether the run has an attributable party, an agent session
  or a terminal login, which the sealed commit records.
- **maintenance** — the post-merge maintenance mechanism and the install paths
  schedule convergence; they decide nothing about its outcome.

<!-- planned:convergence-overlap-and-failure-reporting -->

- **agent_runtime** — whether code loaded from a slug worktree may change a
  registered repository (`local/projects/teleclaude/spec/feature/agent_runtime/isolated-home`,
  UC-IAH10); convergence only reports the roots it is refused.

<!-- /planned:convergence-overlap-and-failure-reporting -->

## Known caveats

- Two computers that converge the same repository before either one pushes
  produce two commits for the same base. The move and rewrite are deterministic,
  so both carry the same content and the histories merge cleanly.
- A linked worktree's branch that touches the earlier layout conflicts with the
  converged commit on rebase or merge. Convergence reports such worktrees and
  does not refuse on them.
- A repository that stays blocked stays invisible to documentation reads until
  its block is cleared and a later run converges it.
- A pull that brings the converged layout leaves behind, in the retired
  directory, the files git never tracked there. When that directory holds only
  the generated catalog and operating-system folder metadata beside its
  converged counterpart, it is residue: an attributable run removes it, names
  the removed files, and reports the root current. Any other file left in it is
  a layout, and the root is blocked by both layouts being present.
