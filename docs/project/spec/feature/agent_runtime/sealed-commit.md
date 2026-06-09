---
id: 'project/spec/feature/agent_runtime/sealed-commit'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Sealed commit interface for agent sessions inside the host pane. The git wrapper blocks raw `git add` / `git commit` and redirects to `telec code commit`, which constructs a pathspec-scoped commit from the resolved workspace scope plus declared `--include` paths. New untracked files, unmerged-index files, and partial-staged tracked files are explicitly accepted by `telec code add`. Cross-session work cannot leak into a commit by construction.'
---

# Sealed Commit — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md
- @docs/project/design/code-commit.md

## What it is

The **sealed commit contract** is the agent-facing channel for landing changes in git. Inside an agent_runtime host pane, agents do not run `git add` or `git commit` directly: the git wrapper intercepts both and redirects to `telec code commit` (and to `telec code add` for the rare cases git's data model genuinely requires staging). The wrapper enforces the seal at the shell level; `telec code commit` enforces the contract internally; the final commit runs with an explicit pathspec so foreign work in the index cannot be swept in.

The contract resolves four classes of file state at commit time:

1. **Modified-tracked** files in scope ride the pathspec straight from the working tree — the commit records the working-tree version, no staging needed.
2. **NEW (untracked)** files in scope are **dropped** from the pathspec unless declared via `telec code add <path>` or `--include <path>`. This is the safety net against incidental temp/scratch artifacts the agent's tool calls may have created.
3. **Partial-staged tracked** files (staged hunks + later working-tree delta) in the pathspec are **blocked** by the partial-staging guard. The diagnostic directs the agent at `telec code add <path>` as the recovery: it fully restages the file so the staged version matches the working tree, removing the ambiguity, after which the commit proceeds cleanly.
4. **Unmerged-index** files (post-conflict, pre-resolution-stage) in the pathspec are staged internally so the integrator's conflict-resolution flow runs through the same sealed path.

The scope itself is strictly `(this session's transcript-touched paths) ∩ (currently dirty paths)`. A deletion of a file that the session did not touch is NOT in scope — closing a previously-existing leak in which agent A's `rm` ended up committed by agent B. Bash-`rm` deletions that fall out of the transcript extractor are declared via `--include <deleted-path>`.

On the repo-root `main` branch, a non-integrator agent invoking `telec code commit` without `--approved` surfaces the **Path A/B/C** classification card and exits — no commit takes place. `--approved` is the human-approved gate that lets the commit proceed; on a worktree or integrator role, `--approved` is still required but the A/B/C surfacing is bypassed.

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

#### Bare telec code commit on main surfaces Path A/B/C

```
Given an agent on the `main` branch with a non-integrator role
When the agent invokes `telec code commit` with no flags
Then the command prints the Path A/B/C classification card to stderr
And exits non-zero without producing a commit
And the card names: A (non-functional + `[skip ci]`), B (small functional + `--approved`), C (functional + reviewer dispatch)
And the card points at `telec code changed` for scope inspection
And the card surfaces `telec code add` and `--include` for new-file declaration
```

#### Approved commit produces a pathspec commit on the resolved scope

```
Given an agent session whose transcript has touched paths {P1, P2, ..., Pn}
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

#### Integrator role bypasses the Path A/B/C surfacing

```
Given the session's system role resolves to integrator
When the integrator invokes `telec code commit --approved "<msg>"` on main
Then the Path A/B/C card is NOT printed
And the commit proceeds (subject to the other invariants — pathspec construction, partial-staging guard, etc.)
And this is justified because every change the integrator commits was individually approved via its delivery's lifecycle
```

### Use cases

- **Routine agent edit-and-commit:** modify tracked files; run `telec code commit --approved "<msg>"`; pathspec ride takes them via working tree; no `git add` ever invoked by the agent.
- **Agent introduces a new file:** `telec code add <new>` before commit (incremental) OR `--include <new>` at commit time (one-shot). Either declares intent so the safety net releases the file.
- **Agent recovers from accidental partial-staging:** `telec code add <file>` fully restages; commit retries cleanly.
- **Integrator conflict resolution after a squash merge:** edit resolved file; `telec code add <resolved>`; `telec code commit --approved "<msg>"`.
- **Bash-`rm` deletion that fell out of transcript:** `telec code commit --approved "<msg>" --include <deleted>` declares the deletion explicitly.

## See also

- docs/project/design/code-commit.md
- docs/project/spec/telec-cli-surface.md
- docs/global/software-development/policy/version-control-safety.md
