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
reference in the qualified identity form (`general/spec/snippet-authoring-schema`).
Nothing reads the earlier layout, so a repository that has not converged is
invisible to indexing, validation, and selection until it does.

Convergence is a documentation-owned maintenance operation. It walks the
project registry, and for each available root it either finds the root current,
converges it with one commit in that root's own repository, or leaves it
unchanged and reports why. A convergence commit is always attributable: a run
with no attributable commit party — no agent session and no terminal login —
changes no root and defers every root that would converge. The layout of the checkout is its own completion
record: a root with neither `docs/project` nor `agents/project` is current, so
every run is idempotent and a convergence that arrived by pull is recognized
without bookkeeping.

A convergence consists of:

- **The move.** `docs/project` becomes `docs/local` and `agents/project` becomes
  `agents/local`.
- **The reference rewrite.** Tracked text is rewritten at the identifier level
  only: paths into the old folders become paths into the new ones; the
  repository's own unqualified local identities become `projects/<slug>/…`
  with the slug the repository declares; person and company identities become
  `people/<slug>/…` and `companies/<slug>/…`; identities prefixed with a
  registered project's slug become `projects/<slug>/…`. Changelogs and
  generated files are never rewritten; a decision record keeps its body, and
  only the paths in its See Also list follow the move. Snippets in the
  repository's published half (`docs/global`) keep their identities; their
  occurrences are reported to the owner, who decides whether each mention means
  that repository or the project at hand.
- **The commit.** One commit in the root's repository through the sealed commit
  path, carrying exactly the moved and rewritten paths.

Convergence runs on every computer: as a post-merge maintenance action on
computers that follow the branch, and from both install paths, which include
tag deployments. Where such a run has no attributable party, the roots it
defers converge on that computer's next attributable run. From an install or a
tag deployment, a non-zero result is printed as a warning and the install or
deployment still completes: no deferred or blocked repository fails a platform
upgrade. The post-merge maintenance action keeps its non-zero result.

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
When layout convergence runs
Then nothing in that repository changes
And the root is reported as current
And a second run over a repository converged by UC-DLC1 reports it current
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

#### UC-DLC8: A refused commit reverses only convergence's own changes

```gherkin
Given a registered repository that UC-DLC1 would converge
And the sealed commit refuses the convergence commit
When layout convergence runs
Then convergence reverses only its own changes: each rewritten file whose bytes still equal what convergence wrote gets its original bytes back, the moved directories are renamed back, and each touched path whose index entry still equals the one convergence staged returns to the committed entry
And a rewritten file whose bytes changed since convergence wrote them, a touched path whose index entry changed since convergence staged it, or a retired directory (docs/project or agents/project) that exists again when the restore begins, is left exactly as found and named
And the root is reported as a restore conflict when any such path exists, and otherwise as restored after a refused commit, with the repository's files and index equal to their state before the run
```

#### UC-DLC9: Published-half mentions and records are reported, not guessed

```gherkin
Given a registered repository converged by UC-DLC1
And its docs/global snippets mention unqualified local identities
When layout convergence completes for that root
Then those docs/global mentions are unchanged
And the root's report lists them for the repository's owner
And changelogs, generated files, and decision-record bodies are unchanged
```

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

#### UC-DLC12: A run without an attributable party changes nothing and defers

```gherkin
Given a layout convergence run with no attributable commit party — no agent session and no terminal login, as in a deploy pull or a tag install
When the run walks the project registry
Then no root is moved, rewritten, or committed
And each root that would converge is reported as deferred for lack of an attributable party
And the report names the command that re-runs convergence
And current roots and roots needing a pull are still reported as such
```

### Cross-context references

- **config** — the project registry's roots and each repository's declared
  project slug. Declarations only; convergence registers nothing.
- **commit** — the sealed commit path is the only way convergence commits in
  another repository; its refusal is final for that run.
- **identity** — whether the run has an attributable party, an agent session
  or a terminal login, which the sealed commit records.
- **maintenance** — the post-merge maintenance mechanism and the install paths
  schedule convergence; they decide nothing about its outcome.

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
