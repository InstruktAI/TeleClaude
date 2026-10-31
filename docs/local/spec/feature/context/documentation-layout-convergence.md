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

An earlier-layout checkout whose upstream already has the converged layout is
left unchanged and reported as needing a pull. Dirty touched paths, a missing
declared slug, or both layout roots present leave only the affected root
unchanged and blocked; the report names each blocking path. A slug comes from
the registry declaration, never from the directory name. Other roots in the
same run may still converge.

If a move, write, stage, or sealed commit fails, rollback restores only bytes,
moves, and index entries that still match convergence's own changes. It leaves
intervening edits and reoccupied paths untouched and reports restore conflicts.
An unattributable run defers roots that need work, changes nothing, and names
the attributable command for a later retry.

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
with no attributable commit party — no agent session and no terminal login, the
computer's operator outside a session included
(`local/projects/teleclaude/spec/identity-and-auth` §2) — changes no root and
defers every root that would converge. The checkout is its
own completion record: a root with neither `docs/project` nor `agents/project`,
whose tracked Markdown names no project-local identity without its `local/`
prefix, is current, so every run is idempotent and a convergence that arrived by
pull is recognized without bookkeeping. A root whose recorded tree still tracks a retired
directory that is gone from the checkout is an interrupted migration: it is
reported blocked, never current.

One run at a time converges a repository on a computer. A run that reaches a
repository another run is converging says it is waiting for that run, waits,
and then reads the repository as it stands, so overlapping runs never act on
one repository together.

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

Convergence runs on every computer: as a post-merge maintenance action on
computers that follow the branch, and from both install paths, which include
tag deployments. Where such a run has no attributable party, the roots it
defers converge on that computer's next attributable run. A run's result tells
three cases apart: every root settled; some root blocked or deferred and none
failed; and some root failed, restored after a refused commit, or in restore
conflict. Both unsettled cases are non-zero, and the post-merge maintenance
action keeps that as its result. How an install responds to each case is
installation's contract
(`local/projects/teleclaude/spec/feature/reconciliation/fresh-machine-bootstrap`).

## Canonical fields

### Use cases

#### UC-DLC1:

```gherkin
Given a maintainer has a registered repository whose folders or project-local references use the earlier documentation layout
When the maintainer runs layout convergence for that repository
Then its documentation and local agent artifacts use the current layout
And its project-local references use qualified identities
And the change is recorded in one commit in that repository
And the root is reported as migrated and committed
```

#### UC-DLC2:

#### UC-DLC3:

#### UC-DLC4:

#### UC-DLC5:

#### UC-DLC6:

#### UC-DLC8:

#### UC-DLC9:

```gherkin
Given a maintainer owns a registered repository whose published documentation contains unqualified local identities
When they review the convergence result
Then those mentions remain unchanged and are listed for the maintainer to resolve
And changelogs, generated files, and decision-record bodies remain unchanged
```

#### UC-DLC10:

#### UC-DLC11:

```gherkin
Given a maintainer runs layout convergence over registered repositories
When the run completes
Then they can tell each root's outcome
And distinguish a failure from roots that are only blocked or deferred
```

#### UC-DLC12:

#### UC-DLC13:

#### UC-DLC14:

#### UC-DLC15:

### Cross-context references

- **config** — the project registry's roots and each repository's declared
  project slug. Declarations only; convergence registers nothing.
- **commit** — the sealed commit path is the only way convergence commits in
  another repository; its refusal is final for that run.
- **identity** — whether the run has an attributable party, an agent session
  or a terminal login, which the sealed commit records.
- **maintenance** — the post-merge maintenance mechanism and the install paths
  schedule convergence; they decide nothing about its outcome.

- **agent_runtime** — UC-IAH10 owns the refusal to change another
  checkout. Convergence reports an outside checkout as out of scope and does not
  count it as blocked, deferred, or failed.

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
