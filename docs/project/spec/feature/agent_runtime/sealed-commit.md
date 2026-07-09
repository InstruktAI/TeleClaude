---
description: 'Sealed commit interface for agent sessions inside the host pane. The git wrapper blocks raw `git add` / `git commit` and redirects to `telec code commit`, which constructs a pathspec-scoped commit from the resolved workspace scope plus declared `--include` paths. New untracked files, unmerged-index files, and partial-staged tracked files are explicitly accepted by `telec code add`. Cross-session work cannot leak into a commit by construction.'
visibility: 'public'
---

# Sealed Commit — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md
- @docs/project/design/code-commit.md

## What it is

The **sealed commit contract** is the agent-facing channel for landing changes in git. Inside an agent_runtime host pane, agents do not run `git add` or `git commit` directly: the git wrapper intercepts both and redirects to `telec code commit` (and to `telec code add` for the rare cases git's data model genuinely requires staging). The wrapper enforces the seal at the shell level; `telec code commit` enforces the contract internally; the final commit runs with an explicit pathspec so foreign work in the index cannot be swept in.

The seal is scoped to telec-registered projects. When the working directory is a plain git repo with no `teleclaude.yml`, the wrapper enforces nothing and execs the real git binary unmodified — the same transparent passthrough it applies outside tmux.

The contract resolves four classes of file state at commit time:

1. **Modified-tracked** files in scope ride the pathspec straight from the working tree — the commit records the working-tree version, no staging needed.
2. **NEW (untracked)** files in scope are **dropped** from the pathspec unless declared via `telec code add <path>` or `--include <path>`. This is the safety net against incidental temp/scratch artifacts the agent's tool calls may have created.
3. **Partial-staged tracked** files (staged hunks + later working-tree delta) in the pathspec are **blocked** by the partial-staging guard. The diagnostic directs the agent at `telec code add <path>` as the recovery: it fully restages the file so the staged version matches the working tree, removing the ambiguity, after which the commit proceeds cleanly.
4. **Unmerged-index** files (post-conflict, pre-resolution-stage) in the pathspec are staged internally so the integrator's conflict-resolution flow runs through the same sealed path.

The scope itself is strictly `(this session's transcript-touched paths) ∩ (currently dirty paths)`. A deletion of a file that the session did not touch is NOT in scope — closing a previously-existing leak in which agent A's `rm` ended up committed by agent B. Bash-`rm` deletions that fall out of the transcript extractor are declared via `--include <deleted-path>`.

On the repo-root `main` branch, a non-integrator agent invoking `telec code commit` without `--approved` surfaces the **commit-first and review-routing gate** and does not commit. A bare invocation (no message) is discovery and **exits 0** — serving the gate is the successful outcome; an invocation that carries a message but omits `--approved` means the gate was forgotten and **exits non-zero**. `--approved` is the agent-owned sealed-gate acknowledgment that lets the commit proceed; it is not human approval. On a worktree or integrator role, `--approved` is still required but the gate surfacing is bypassed.

## Canonical fields

### Use cases

#### Wrapper redirects raw git commit to telec code commit

```
Given an agent session running inside its host pane (identity present)
When the agent invokes `git commit` in any form
Then the wrapper prints an error pointing at `telec code commit`
And exits non-zero without producing a commit
And there is no env-var bypass on the commit branch
```

#### Wrapper redirects raw git add to telec code add

```
Given an agent session running inside its host pane
When the agent invokes `git add` with any arguments (`-A`, specific path, `--` pathspec, etc.)
Then the wrapper prints an error pointing at `telec code add` for NEW files and `telec code commit` for the routine case
And exits non-zero without staging anything
And inspection commands (`git diff`, `git status`, `git log`) remain available
```

#### Wrapper passes through transparently outside a telec-registered project

```
Given an agent session running inside its host pane (identity present)
And the working directory is a git repo with no `teleclaude.yml` (not a telec-registered project)
When the agent invokes `git add`, `git commit`, `git rebase`, or `git push` in any form
Then the wrapper execs the real git binary unmodified
And no seal or role-guard error is printed
And the command's exit status and output are git's own
```

#### Bare telec code commit on main surfaces the commit-first review-routing gate

```
Given an agent on the `main` branch with a non-integrator role
When the agent invokes `telec code commit` with no message and no flags
Then the command prints the commit-first review-routing gate to stderr
And exits 0 — serving the gate is the successful outcome, not a failure
And the gate routes review by what the diff touches: functional code/tests → agent-judged med code review; doc snippets (docs/**) or agent artifacts (agents/**) → required fast doc-hygiene review; neither → no review
And the gate points at `telec code changed` for scope inspection
And the gate surfaces `telec code add` and `--include` for new-file declaration
```

#### telec code commit with a message but no --approved is a forgotten gate

```
Given an agent on the `main` branch with a non-integrator role
When the agent invokes `telec code commit "<message>"` without `--approved`
Then the command prints the commit-first review-routing gate to stderr without producing a commit
And exits non-zero without producing a commit
```

#### Doc-snippet commit on main requires an independent doc-hygiene review

```
Given an agent on `main` commits a change that touches a doc snippet (docs/**)
When the commit lands via `telec code commit --approved`
Then an independent fast-or-medium reviewer runs the doc-hygiene lane over the changed snippets on the commit SHA via `/next-review-commits`
And the agent reuses the reviewer already open for the patch series, or starts one if none is open — never a second
And the authoring agent never reviews a snippet it wrote
And a config/state/README-only commit with no doc snippet requires no review
```

#### Approved commit produces a pathspec commit on the resolved scope

```
Given an agent session whose transcript has touched paths {P1, P2, ..., Pn}
And another agent session is concurrently live on the same shared checkout
When the agent invokes `telec code commit --approved "<message>"`
Then the resolved scope = (touched paths) ∩ (currently dirty paths)
And new untracked paths in scope are dropped from the pathspec
And the final commit runs with pathspec = (scope minus untracked-not-staged)
And anything else in the index (foreign-staged, crash residue) is left untouched
And the mandated TeleClaude trailer is appended to the message if absent (idempotent)
```

#### Modified-tracked files ride the pathspec without staging

```
Given an agent has edited a tracked file `foo.py` in the working tree
And the agent has NOT run `telec code add foo.py`
When the agent invokes `telec code commit --approved "<message>"`
Then no internal staging is performed on `foo.py`
And the final commit on `foo.py` records the working-tree version
And no partial-staging guard fires
```

#### NEW untracked files in scope are dropped without explicit declaration

```
Given an agent has created an untracked file `scratch.txt` via tool calls
And the file is in the session's transcript-touched set
And the agent has NOT run `telec code add scratch.txt` or `--include scratch.txt`
When the agent invokes `telec code commit --approved "<message>"`
Then the commit's stderr surfaces a reminder naming `scratch.txt` and the two declaration paths
And `scratch.txt` is NOT in the final commit's pathspec
And `scratch.txt` remains untracked in the working tree
And HEAD's tree does not contain `scratch.txt`
```

#### --include extends the pathspec with declared paths

```
Given an agent has edited `mine.py` (in scope) and created `extra.py` (in scope, untracked)
When the agent invokes `telec code commit --approved "<msg>" --include extra.py`
Then the final pathspec = (scope-tracked) ∪ {extra.py}
And `extra.py` is staged internally before the commit (because it is untracked)
And both `mine.py` and `extra.py` are recorded in HEAD's tree
And foreign-staged files in the index remain untouched
```

#### --include of a clean path errors

```
Given a path `clean.py` that has no working-tree changes and is not staged
When the agent invokes `telec code commit --approved "<msg>" --include clean.py`
Then the command prints an error naming `clean.py`
And exits non-zero without producing a commit
```

#### --include with no operand errors fast

```
Given the agent invokes `telec code commit --approved "<msg>" --include` with no following path
Or `telec code commit --approved "<msg>" --include <p1> --include` (second group empty)
Or `telec code commit --include --approved "<msg>"` (operand-group closed by --approved)
When the parser closes the include group with zero operands
Then the command prints an error requiring at least one operand
And exits non-zero without producing a commit
```

#### Partial-staging guard blocks silent contamination

```
Given a tracked file `foo.py` is partial-staged (staged version A + later working-tree edit B)
And `foo.py` is in the resolved pathspec
When the agent invokes `telec code commit --approved "<msg>"`
Then the partial-staging guard detects the overlap (staged ∩ unstaged ∩ pathspec)
And the command prints the offending paths and points at `telec code add <foo.py>` as recovery
And exits non-zero without producing a commit
And HEAD's object id is unchanged
```

#### telec code add recovers partial-staged tracked files

```
Given a tracked file `foo.py` is partial-staged (staged + later unstaged delta)
When the agent invokes `telec code add foo.py`
Then the file is fully restaged internally
And the staged version matches the working-tree version
And a subsequent `telec code commit --approved "<msg>"` proceeds without the guard firing
```

#### telec code add accepts NEW untracked files

```
Given a new file `new.py` exists in the working tree (untracked)
When the agent invokes `telec code add new.py`
Then `new.py` is added to the index
And it now appears in the staged set
And a subsequent `telec code commit --approved "<msg>"` includes it in the pathspec
```

#### telec code add accepts unmerged-index files (integrator conflict path)

```
Given a squash merge in the integration worktree produced an unmerged-index entry for `resolved.py`
And the integrator manually resolved the conflict in the working tree
When the integrator invokes `telec code add resolved.py`
Then the file is staged internally
And the unmerged-index entry is replaced with a single staged resolved entry
And a subsequent `telec code commit --approved "<msg>"` records the resolution
```

#### telec code add no-ops cleanly-modified tracked files

```
Given a tracked file `mod.py` has only an unstaged working-tree edit (not partial-staged, not unmerged, not new)
When the agent invokes `telec code add mod.py`
Then no staging occurs
And the command emits no error
And the file remains a modified-tracked file ready to ride the next commit's pathspec
```

#### telec code add rejects clean and missing paths

```
Given a path `clean.py` that is tracked with no pending changes
When the agent invokes `telec code add clean.py`
Then the command prints an error naming the path
And exits non-zero

Given a path `does-not-exist.py` that is not in the working tree
When the agent invokes `telec code add does-not-exist.py`
Then the command prints an error naming the path as not found
And exits non-zero
```

#### Cross-session deletion does not leak into scope

```
Given agent A's tool calls deleted `foreign.py` in the working tree
And agent B's transcript has touched `mine.py` (NOT `foreign.py`)
And both deletions appear in `git status --porcelain` as dirty
When agent B's workspace-scope resolution runs
Then the resolved scope contains only `mine.py`
And `foreign.py` is NOT in agent B's scope
And agent B's subsequent `telec code commit --approved` records only `mine.py` in HEAD
And `foreign.py` remains a pending working-tree deletion for agent A to commit or recover
```

#### Foreign staged files in the index are not swept by the pathspec

```
Given another session has staged `foreign.py` to the index
And this session's pathspec is {mine.py}
When this session invokes `telec code commit --approved "<msg>"`
Then the final commit on `mine.py` records only `mine.py` in HEAD
And `foreign.py` remains in the index for its owner
And no foreign-staged-file diagnostic is emitted (the pathspec alone is the boundary)
```

#### --approved without a message errors

```
Given the agent invokes `telec code commit --approved` with no message
When the parser validates positional arguments
Then the command prints an error requiring a quoted message
And exits non-zero without producing a commit
```

#### Integrator role bypasses the gate surfacing

```
Given the session's system role resolves to integrator
When the integrator invokes `telec code commit --approved "<msg>"` on main
Then the commit-first review-routing gate is NOT printed
And the commit proceeds (subject to the other invariants — pathspec construction, partial-staging guard, etc.)
And this is justified because every change the integrator commits was individually approved via its delivery's lifecycle
```

### Use cases

- **Routine agent edit-and-commit:** modify tracked files; run `telec code commit --approved "<msg>"`; pathspec ride takes them via working tree; no `git add` ever invoked by the agent.
- **Agent introduces a new file:** `telec code add <new>` before commit (incremental) OR `--include <new>` at commit time (one-shot). Either declares intent so the safety net releases the file.
- **Agent recovers from accidental partial-staging:** `telec code add <file>` fully restages; commit retries cleanly.
- **Integrator conflict resolution after a squash merge:** edit resolved file; `telec code add <resolved>`; `telec code commit --approved "<msg>"`.
- **Bash-`rm` deletion that fell out of transcript:** `telec code commit --approved "<msg>" --include <deleted>` declares the deletion explicitly.

### Commit-time gates — in-process, no framework stash

`telec code commit` runs format then lint in-process against `quality_paths`
(the commit pathspec filtered to existing files) before `git commit --no-verify`.
No framework stash occurs; files outside the pathspec are not touched. The
installed `.git/hooks/pre-commit` is a thin telec-owned guard performing only a
partial-staging check as a backstop for raw `git commit` invocations.

#### UC-CGIP-1 — Commitizen format check blocks malformed message

```
Given message does not match type(scope): subject or type: subject
When agent invokes telec code commit --approved "<bad-message>"
Then SystemExit(1) before format/lint/git-commit invoked
```

#### UC-CGIP-2 — Gates run format-before-lint against quality_paths

```
Given pathspec contains existing and deleted files
When agent invokes telec code commit --approved "<msg>"
Then quality_paths = pathspec filtered to existing files only
And handle_format(quality_paths) is called before handle_lint(quality_paths)
```

#### UC-CGIP-3 — Deletion-only commit bypasses format/lint

```
Given pathspec contains only a deleted file
When agent invokes telec code commit --approved "<msg>"
Then quality_paths is empty
And neither handle_format nor handle_lint is invoked
And git commit --no-verify proceeds
```

#### UC-CGIP-4 — Clean commit proceeds with --no-verify

```
Given format and lint both pass on quality_paths
When agent invokes telec code commit --approved "<msg>"
Then repo.git.commit is called with "--no-verify" in its args
And no framework stash occurs
```

#### UC-CGIP-5 — Format failure blocks commit

```
Given format fails on quality_paths
When agent invokes telec code commit --approved "<msg>"
Then SystemExit(1) before repo.git.commit invoked
```

#### UC-CGIP-6 — Lint failure blocks commit

```
Given lint fails on quality_paths (after format passed)
When agent invokes telec code commit --approved "<msg>"
Then SystemExit(1) before repo.git.commit invoked
```

#### UC-CGIP-7 — Lock releases cleanly on gate failure

```
Given handle_lint raises SystemExit(1)
When telec code commit --approved "<msg>" is invoked
Then main_branch_lock __exit__ is called (lock released)
```

#### UC-CGIP-8 — Bare commit surfaces the gate and exits 0

```
Given a non-integrator agent invokes telec code commit with no message and no --approved
When the branch is main (commit-first review-routing gate) or any other branch (short help)
Then the guidance is printed and no commit occurs
And SystemExit(0) — serving the gate is the successful outcome of a bare invocation
```

#### UC-CGIP-9 — Message without --approved is a forgotten gate

```
Given a non-integrator agent invokes telec code commit "<message>" without --approved
When the branch is main
Then SystemExit(1) and no commit occurs
And on any other branch SystemExit(2)
```

#### UC-CGIP-10 — Merge commit degrades to a full-index commit with no pathspec

```
Given MERGE_HEAD is present (an active merge, resolved via repo.git_dir so it holds inside worktrees)
And every conflicted path has been resolved and staged (no remaining unmerged-index entries)
When agent invokes telec code commit --approved "<msg>"
Then quality_paths is the full merge diff (merge-base..MERGE_HEAD), not the caller's pathspec
And handle_format(quality_paths) is called before handle_lint(quality_paths)
And repo.git.commit is called with "--no-verify" and no trailing "--" pathspec
And the resulting commit records origin/main as a merge parent
```

#### UC-CGIP-11 — Unresolved conflict during merge commit is rejected

```
Given MERGE_HEAD is present and one or more paths remain unmerged (not yet telec code add-ed)
When agent invokes telec code commit --approved "<msg>"
Then SystemExit(1) listing the unresolved paths
And no commit occurs
And neither handle_format nor handle_lint is invoked
```

#### UC-CGIP-12 — Slug worktree refuses doc-layer paths

```
Given a slug worktree at trees/<slug> (a worktree that is not trees/_integration)
And the resolved commit pathspec contains one or more paths under docs/**
When agent invokes telec code commit --approved "<msg>"
Then SystemExit(1) naming each offending docs/** path
And no commit occurs
And neither handle_format nor handle_lint is invoked
And the refusal directs the agent at the kickback route telec todo stamp <slug> --kickback --reason "<why>"
```

#### UC-CGIP-13 — Main branch and integration worktree are unaffected by the doc refusal

```
Given the commit pathspec contains a path under docs/**
When the invocation is on the repo-root main branch, or in the integration worktree at trees/_integration
Then the doc refusal does not fire
And the commit proceeds subject to the other commit-time invariants
```

#### UC-CGIP-14 — A session with no resolvable transcript scopes to empty, not to an error

```
Given a telec code invocation bound to an agent session on the repo-root shared branch
And that session has no resolvable transcript to scope its changes from
When the workspace scope is resolved
Then the session's touched-path scope resolves as empty and the resolution returns normally
And telec code commit applies its documented empty-scope behavior, leaving --include as the agent's channel to declare paths
And no path the session did not touch is admitted to the commit pathspec by the empty resolution
And the empty resolution never widens to the dirty worktree
```

<!-- planned:distinguish-undetermined-scope-from-empty-scope -->

#### UC-CGIP-15 — telec code changed reports an undetermined scope as undetermined, not as no changes

```
Given a telec code invocation bound to an agent session on the repo-root shared branch
And that session has no resolvable transcript to scope its changes from
When the agent runs telec code changed
Then the output states that the workspace scope could not be determined
And the output names --include as the channel for declaring paths
And the output does not claim the session has no uncommitted changes
```

#### UC-CGIP-16 — telec code commit on an undetermined scope names the declaration channel

```
Given a telec code invocation bound to an agent session on the repo-root shared branch
And that session has no resolvable transcript to scope its changes from
And the agent has uncommitted work in the repository
When the agent runs telec code commit with an approved message and declares no paths
Then the commit is refused with a non-zero exit
And the diagnostic states that the workspace scope could not be determined
And the diagnostic names --include and --only as the channels for declaring paths
And no commit is produced
```

#### UC-CGIP-17 — telec code changed on a resolved empty scope still reports no changes

```
Given a telec code invocation bound to an agent session on the repo-root shared branch
And that session owns a resolvable transcript that touched no dirty path
When the agent runs telec code changed
Then the output states that there are no uncommitted workspace-scoped changes
And the output does not suggest that the scope could not be determined
```

<!-- /planned:distinguish-undetermined-scope-from-empty-scope -->

### Thin hook backstop

#### UC-TH-1 — Thin hook partial-staging backstop

```
Given agent bypasses telec and invokes raw git commit with partially staged files
When the thin .git/hooks/pre-commit runs
Then it detects the overlap via NUL-safe Python (no unquoted shell expansion)
And exits non-zero naming the partially staged paths
And no INSTALL_PYTHON is present in .git/hooks/pre-commit
```

#### UC-TH-2 — Thin hook passes clean commits

```
Given working tree has no partially staged files
When raw git commit is attempted
Then .git/hooks/pre-commit exits 0
And the commit proceeds (gates were enforced in-process by telec code commit)
```

#### UC-TH-3 — Thin hook fails closed on git status probe failure

```
Given the git status probe (git status --porcelain=v1 -uall -z) returns nonzero
When the thin .git/hooks/pre-commit runs
Then the hook exits nonzero immediately
And the commit is aborted
And the partial-staging check is NOT silently bypassed
```

## See also

- docs/project/design/code-commit.md
- docs/global/general/spec/tools/telec-cli.md
- docs/global/software-development/policy/version-control-safety.md
