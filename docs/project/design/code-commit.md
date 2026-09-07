---
description: 'Design of telec code commit — the canonical agent commit command with workspace-scope staging and pathspec-scoped commits.'
visibility: 'public'
---

# Code Commit — Design

## Required reads

@~/.teleclaude/docs/software-development/policy/commits.md

## Purpose

`telec code commit` is the canonical commit interface for **autonomous agent
sessions inside tmux**. It resolves the workspace scope and runs `git commit`
with an explicit pathspec.

The staging model is asymmetric and follows git's data model:

- **Modified-tracked files in scope** that are NOT partial-staged ride the
  pathspec straight from the working tree — `git commit -- <path>` records
  the working-tree version, no staging needed.
- **Partial-staged tracked files** in the commit pathspec (staged hunks +
  later working-tree delta) are BLOCKED by the partial-staging guard —
  `git commit -- <path>` would otherwise sweep unstaged hunks the agent
  did not declare into the commit. The blocking diagnostic points the
  agent at the recovery: `telec code add <path>` fully restages the file
  so the staged version matches the working tree, eliminating the
  ambiguity, after which `telec code commit` proceeds cleanly.
- **NEW (untracked) files in scope** are NOT auto-committed. The agent must
  declare them via `telec code add <path>` (sealed equivalent of `git add`)
  or `--include <path>` at commit time. This is the safety net against
  incidental temp/scratch artifacts the agent's tool calls may have created.
- **Unmerged-index files in pathspec** (post-conflict, pre-resolution-stage)
  are staged internally via `_stage_files` so the integrator's conflict
  resolution flow runs through the same sealed path.


`telec code commit` runs the gates carried by the acting invocation context's
declared tier. Where that tier carries project subscriptions, it runs format then
lint in-process against `quality_paths` (the commit pathspec filtered to existing
files) before `git commit --no-verify`; where it carries none, neither runs and
nothing is applied in their place. No framework stash, no working-tree reset
outside the pathspec. The installed `.git/hooks/pre-commit` is a thin telec-owned
guard that performs only a partial-staging check as a backstop for raw
`git commit` invocations.


The git wrapper redirects raw `git commit` (and `git add`) to this command
for tmux callers.

**Caller paths:**


A commit reaches git through one of four contexts in this repository: the human
shell outside tmux, an autonomous agent inside tmux within a telec-registered
project, an agent inside tmux within a repository whose own root is a declared
invocation context that is not a project, and an agent inside tmux operating in a
repository whose own root carries no declaration.

| Caller context                                  | Command                            | Why telec is or isn't involved                                                                                                                             |
| ----------------------------------------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Outside tmux (human shell)                      | `git commit ...`                   | The wrapper passes through to real git directly when `$TMUX` is unset. No identity check, no env var, no telec.                                            |
| Inside tmux, autonomous agent (registered)      | `telec code commit --approved ...` | Lock + workspace scope + pathspec commit. The body of this design.                                                                                         |
| Inside tmux, repository root a declared context | `telec code commit --approved ...` | Sealed on the repository's own declaration rather than on project subscriptions; an invocation beneath it resolving to no context root is refused.         |
| Inside tmux, repository root undeclared         | `git commit ...`                   | The repository's own root carries no declaration → the wrapper enforces nothing and execs real git unmodified, as it does outside tmux.                    |


Inside tmux there is **no env-var bypass on `git commit`**. The wrapper
redirects every `git commit` invocation to `telec code commit` with no
override. `--include` is the only way to extend the commit pathspec beyond
the resolved workspace scope, and the agent must name every path it claims.

**Wrapper-enforced intent layer:**

The git wrapper enforces the intent layer for every git invocation in a
tmux session. `telec code commit` runs on top of these guarantees.


Every row below presupposes the git invocation targets a sealed repository. A
telec-registered project that subscribes `code` or `docs` — a working tree under
a checkout carrying `teleclaude.yml` whose manifest subscribes at least one of
`code` or `docs` (`project/spec/feature/config/project-capability-manifest`) — is
one; the commit-interception rows follow that `code ∨ docs` condition, while the
worktree and branch-discipline rows additionally require `code`. A repository
whose own root is a declared non-project invocation context is also one, and
there the seal covers the whole repository: an invocation beneath it resolving to
no context root is refused rather than passed through. A project root's seal
follows its subscriptions alone — a project subscribing neither capability keeps
ordinary git exactly as stated below, whatever else its tier answers. When the project subscribes neither, or the
repository's own root carries no declaration at all, the wrapper decides nothing
from this matrix: it execs the real git binary unmodified, the same transparent
passthrough it applies outside tmux.



The wrapper reads capability state from the repository root's `teleclaude.yml`
— the same declaration the runtime resolves — deriving `code ∨ docs` for commit
interception and `code` for worktree and branch discipline. It reads the file
directly in shell, spawning no interpreter, so the read costs less than
locating a projected copy would. It reads the declaration's tier first. A
project declaration carries the capability blocks: a block that is absent, or
present without an `enabled` value, leaves that capability subscribed, which is
the typed overlay's own default, so a project onboarded before the manifest
keeps its pre-manifest behavior; a block carrying an unquoted boolean is
honoured as written. A global or person declaration carries no subscriptions:
the repository is sealed on the declaration alone, so the commit-interception
rows and the main-branch replay and push rows apply there, while the worktree
and destructive-operation rows follow `code`, which no non-project tier
carries. A company declaration anchors no context and seals nothing: the
wrapper execs the real git binary unmodified.

A declaration the wrapper cannot resolve — no readable tier, or a capability
block whose value is not a boolean — refuses the git invocation with a message
naming `teleclaude.yml` and the field, and substitutes no capability state. The
wrapper and the runtime answer alike for every declared tier and for every
capability block carrying an unquoted boolean. They part on two inputs: a block
whose value the runtime coerces from a quoted string or a number is refused by
the wrapper, and a declaration whose capability blocks are well-formed but which
fails validation elsewhere in the overlay is refused by the runtime and honoured
by the wrapper, which reads only the tier and the capability blocks
(`project/spec/feature/config/project-capability-manifest`).


The full matrix of wrapper-gated operations, by role and by execution
context. Read columns left-to-right; the first column that decides the
op wins.

| Operation                                                                     | Worker (worktree or repo root) | Integrator (in `trees/_integration/`) | Active merge (`MERGE_HEAD` present) | Rationale             |
| ----------------------------------------------------------------------------- | ------------------------------ | ------------------------------------- | ----------------------------------- | --------------------- |
| `git status`, `git log`, `git show`, `git diff <ref>..<ref>`, `git rev-parse` | ✅ allowed                     | ✅ allowed                            | ✅ allowed                          | Read-only inspection. |

| `git add` (any form) | ❌ blocked → `telec code add` | ❌ blocked → `telec code add` | ❌ blocked → `telec code add` | Staging is telec's job; sealed-commit pathspec depends on it. Also the resolved-conflict recovery path during an active merge. |

| `git commit` | ❌ blocked → `telec code commit` | ❌ blocked → `telec code commit` | ⚠️ `telec code commit` (full commit, no pathspec — single-owner trees only) | Sealed commit contract; no env-var bypass. Mid-merge, git refuses any pathspec-scoped commit (`fatal: cannot do a partial commit during a merge`) regardless of pathspec completeness, so in a single-owner tree `telec code commit` degrades to a full-index commit, which carries only that one owner's resolved state. In a repository whose own root is a declared non-project invocation context the tree has more than one owner, and there the commit preserves the eligible set or is refused; it never degrades to the whole index. An ordinary project checkout is a single-owner tree and keeps this row's existing behavior unchanged. |


| `git reset HEAD <path>` / `git reset -- <path>` (pathspec) | ✅ allowed | ✅ allowed | ✅ allowed | Path-scoped unstage; index-only effect. |
| `git reset` (no pathspec) | ❌ blocked | ❌ blocked | ❌ blocked | Discards staged state non-locally. |
| `git reset --hard\|--merge\|--keep` | ❌ blocked | ❌ blocked | ❌ blocked | Discards commits / merge state. |
| `git restore <path>` (working-tree revert to HEAD) | ✅ allowed | ⚠️ `--confirmed` required | ⚠️ `--confirmed` required | Same risk as `git checkout HEAD -- <path>`. Worktree-only blast radius elsewhere; in the integration worktree the working tree feeds DELIVERY_BOOKKEEPING. |
| `git restore --staged <path>` | ✅ allowed | ✅ allowed | ✅ allowed | Index-only effect; same as `git reset -- <path>`. |
| `git restore --source <ref> <path>` | ✅ allowed | ⚠️ `--confirmed` required | ⚠️ `--confirmed` required | Pulls foreign content from `<ref>` into working tree; same risk surface as `git checkout <ref> -- <path>`. |
| `git checkout -- <path>` (no ref) | ✅ allowed | ⚠️ `--confirmed` required | ⚠️ `--confirmed` required | Working-tree revert to HEAD; same gating as `git restore <path>`. |
| `git checkout <ref> -- <path>` | ✅ allowed | ⚠️ `--confirmed` required | ⚠️ `--confirmed` required | Foreign-ref content into working tree. |
| `git checkout <branch>` / `git switch` | ❌ blocked | ❌ blocked | ❌ blocked | Branch switching loses workspace; not how agents change branches. |
| `git stash*` | ❌ blocked (absolute, no role override) | ❌ blocked | ❌ blocked | Stash captures every dirty file in the worktree it runs in — no pathspec granularity. In a multi-agent repo, a stash lifts other agents' WIP; the pop either silently re-stages foreign content or conflicts with no clean recovery. The integrator's recovery when repo-root sync finds dirty files is to halt and surface to the human (per the integration procedure), never to stash. |
| `git clean` | ❌ blocked | ❌ blocked | ❌ blocked | Deletes untracked files; rarely the right answer for agents. |
| `git revert <commit>` | ⚠️ `--confirmed` required | ⚠️ `--confirmed` required | ⚠️ `--confirmed` required | Multi-agent commits often span scopes; inspection precedes revert. |
| `git merge`/`rebase`/`cherry-pick` on main | ❌ unless integrator role or `TELECLAUDE_OVERRIDE_APPROVED=1` | ✅ allowed | (n/a) | Replays produce commits via paths that bypass `telec code commit`'s sealed commit gate. |
| `git push origin main` | ❌ blocked | ✅ allowed (from integration worktree) | (n/a) | Only the integrator publishes to canonical main. |

**Legend.** ✅ = allowed; ❌ = wrapper blocks with diagnostic; ⚠️ = blocked
without the `--confirmed` flag, allowed with it. `--confirmed` is a
deliberate friction: the wrapper requires the agent to re-run the
exact command with `--confirmed` appended after reading the printed
inspection checklist.

**The slug-worktree extras.** Inside `trees/<slug>` — any worktree other than
`trees/_integration/` — an invocation whose ref-position arguments (those before
`--`) name the local `main` branch (`main`, `heads/main`, `refs/heads/main`, or a
range with one of those as an endpoint) is blocked for every subcommand, read-only
inspection included. There is no `--confirmed` form and no override variable.
`origin/main` is the only main-shaped ref a slug worktree may name; a pathspec
after `--` is never read as a ref.

**The integration-worktree extras** matter because the worktree's index
and working tree are owned by the state machine's
`DELIVERY_BOOKKEEPING` step, which commits whatever is staged with no
path filter. Any mutation introduced from outside the state machine can
produce a delivery-reverting commit on origin/main. `--confirmed` is
the integrator's deliberate ratification that the inspection has
happened.

**Wrapper defaults:** `rebase.autoStash` and
`merge.autoStash` are forced off on every wrapper-driven git call.
`git add -A`/`git add --all`/`git add .` are blocked on main for
non-integrators regardless of the table above — staging on main always
names files explicitly.

## Inputs / Outputs

Sealed contract — exactly:

- `"<message>"` — one quoted commit message (required when `--approved`).
- `--approved` — agent-owned sealed-gate acknowledgment. Absence triggers
  commit-first and post-commit review-routing guidance; it is not a human
  approval signal.
- `--include <path> [<path> ...]` — declare files outside the resolved
  workspace scope that must be in this commit (e.g., a file the human
  collaboratively edited that the scope heuristic missed). Each declared
  path must contribute a change; clean paths are rejected.

Nothing is forwarded to git: no `-m`, no `-F`, no `--`, no bare pathspecs.
The pathspec commit is built internally from `workspace scope plus
--include paths`.

**Outputs:** committed changeset, or failure with actionable diagnostics.

## Invariants

1. **Lock serialisation.** `main_branch_lock()` (flock on
   `GIT_MAIN_LOCK_PATH`) serialises the entire `_commit_under_lock` body.
   No two agents can be inside their commit phase at the same time. The
   lock auto-releases on process exit or crash.

   Stale `.git/index.lock` self-heal: immediately after acquiring the
   flock, `_commit_under_lock` calls `wait_for_index_lock_clear()`. Two
   removal paths: `lsof` shows no process holding the lock AND mtime
   ≥ 10s (orphan signature, fast path), or mtime ≥ 180s (hung-holder
   ceiling, slow path). Polls every 5s with structured logs at every
   state. Self-healing without ever discarding an active git process's
   work. The Python flock does not prevent orphan `index.lock` —
   different lock, different file, owned by git itself — so this check
   is the only protection against a previous git process that was
   killed mid-write.

2. **Workspace scope is authoritative — for pathspec construction, not staging.**
   `resolve_workspace_scope_resolution()` is the single owner of
   worktree-vs-shared-branch scope. The scope set drives the commit's
   pathspec (with `--include` adding explicit, agent-declared paths and
   untracked-not-staged files dropped); it does **not** drive staging.
   Staging is a narrow follow-up step that runs only on the three cases
   git's data model genuinely requires it for: untracked files in the
   pathspec, unmerged-index files in the pathspec, and partial-staged
   tracked files (handled via `telec code add` recovery). Modified-tracked
   files in the pathspec are committed straight from the working tree —
   `git commit -- <path>` records the working-tree version.

3. **Pathspec on commit IS the boundary.** The final `git commit` runs with an
   explicit pathspec equal to `workspace scope plus --include paths` (minus
   untracked-not-staged scope files). Anything else in the index — concurrent
   stage from another session, crash residue from a prior failed commit,
   human-staged files outside the agent's scope — is **invisible to the
   pathspec** and stays staged for its owner. There is no separate
   "foreign-staged" check; the pathspec alone enforces the boundary. Agents
   must not unstage foreign files they see in the index.


4. **The gates the acting tier carries run in-process before `git commit --no-verify`.**
   Where the acting invocation context's declared tier carries project
   subscriptions, `telec code commit` runs `handle_format` then `handle_lint`
   against `quality_paths` (the commit pathspec filtered to existing files)
   before invoking `git commit --no-verify`. Where that tier carries none,
   neither runs and nothing is applied in their place. Deletion-only commits
   (empty `quality_paths`) skip both steps wherever they would otherwise run. The
   thin `.git/hooks/pre-commit` performs only a partial-staging backstop; it does
   not re-run format or lint.


5. **Commit-first gate on main.** Non-integrator agents on main use the bare
   `telec code commit` invocation to surface commit-first and post-commit
   review-routing guidance. They then commit with `--approved`; the committed
   diff determines whether a post-commit review is required or recommended per
   `software-development/policy/commits`. This design owns the mechanics; the
   policy owns the behavioral rule.

6. **Orchestrator restriction.** Orchestrators cannot commit on any branch.

7. **Wrapper redirect.** The git wrapper blocks `git commit` and directs agents
   to `telec code commit`. The wrapper retains all other safety blocks
   (stash, checkout, restore, clean, reset, push on main).

8. **Real git bypass for the inner commit.** The final `git commit --no-verify`
   call uses the real git binary (via GitPython) so the wrapper's redirect does
   not loop back into telec.


9. **`MERGE_HEAD`-aware commit degrades the pathspec boundary where the tree has
   one owner.** When `MERGE_HEAD` is present (resolved via `repo.git_dir`, not a
   literal `.git/` path, so this holds inside worktrees), git categorically
   refuses a pathspec-scoped commit during an active merge, independent of
   whether the pathspec happens to cover the entire resolved index. In a
   single-owner tree — a worker's own worktree, the integration worktree, a
   project checkout — Invariant 3's pathspec boundary therefore does not apply:
   `telec code commit` requires every unmerged path already resolved
   (`telec code add`-ed) — it errors out listing any that remain rather than
   committing an unresolved conflict — then runs the acting tier's gates over the
   full merge diff (not the caller's pathspec) and commits with no pathspec at
   all: `git commit -F <msg> --no-verify` with no trailing `-- <pathspec>`.

   In a repository whose own root is a declared non-project
   invocation context the tree has more than one owner: such a tree is multi-context and concurrently dirty by design, so the
   resolved index can hold another context's material. There a commit taken mid-
   merge preserves the eligible set or is refused; it never degrades to recording
   the whole index.



10. **Two roots resolve as a pair, once, at the entry points.** Every
    `telec code` verb resolves the invocation context root (the nearest
    declaration above the invocation directory) and the repository root (the
    nearest git checkout above it) as distinct coordinates and threads both to
    everything downstream. The repository root anchors git operations and the
    paths git reports; the invocation context root anchors permission (its
    declared tier's answers, read from the config context's tier-permission
    contract), the eligible set's containment bound, and the coordinates in
    which answers are expressed. Where the two coincide — every project
    checkout — the pair degenerates to the single root and nothing observable
    changes.

11. **Own material and the retained set bound eligibility on every route.**
    Own material — what lies under the acting context root minus what belongs
    to another owner: a different declared tier, a context of its own, or a
    repository of its own — bounds the computed scope and every explicitly
    declared path (`--include`, `--only`, `telec code add`) alike; a declared
    path outside it is refused, never carried. The retained-set term consumes
    the reconciliation context's published membership answer where one is
    published — a three-result answer per path, of which only `retained`
    admits, `not-retained` and `outside` alike excluding; a repository whose
    owner publishes none carries no such term, and this surface neither
    decides membership nor substitutes an answer in either case.


12. **Config publishes facts at two coordinates; this contract owns both
    decisions.** The tier answers config publishes grant no operation. Seal
    coverage — whether raw git is intercepted anywhere in a checkout — is this
    contract's rule, decided from the **repository root's** declared tier,
    because the seal is a property of the repository and must hold at
    locations resolving to no context root. Commit availability and gate
    selection are likewise this contract's rules, decided from the **acting
    invocation context root's** invocation-context and project-subscription
    answers; the authority for a non-project context committing at all is the
    approved product contract, never a permission read off an axis. The
    wrapper learns the repository root's tier by reading the tier declaration
    in that root's `teleclaude.yml` — the same field the resolver reads — so
    the two answer alike for every declared tier, and a root whose declaration
    carries no readable tier is refused rather than resolved to any tier.


13. **Inspection and commit consume one payload resolution, with the same
    inputs.** The eligible payload — computed scope bounded per invariant 11,
    minus what the commit itself would drop, plus declared paths — is resolved
    by one function that both `telec code changed` and `telec code commit`
    consume. The observation surface accepts every payload-shaping declaration
    the commit accepts — the explicit include and subset channels among them —
    so an agent previews the payload of exactly the commit it is about to
    make, deletions included, in the acting context root's coordinates. The
    two surfaces are forbidden to project differently: given the same
    declarations, the pre-commit answer equals the final commit pathspec path
    for path, because it is the same computation with the same inputs, not a
    reconciled pair.


## Primary flows


Every walkthrough below traces an acting context whose declared tier carries project subscriptions, so its gate steps are the ones that tier carries. In a context whose tier carries none, the same flows run with no gate step at all.


### Agent commit (worktree)

```
telec code commit --approved "feat(scope): subject"
  → commit gate satisfied (--approved present)
  → lock acquired
  → wait_for_index_lock_clear (self-heal any stale .git/index.lock)
  → workspace scope = WORKTREE → all dirty paths
  → pathspec = scope (no includes)
  → drop untracked-new files from pathspec (require explicit declaration)
  → stage ONLY untracked-or-unmerged files that are in pathspec
    (modified-tracked files are NOT staged — they ride the pathspec)
  → partial-staging guard: block if any pathspec file has both staged
    and unstaged changes
  → quality_paths = pathspec filtered to existing files
  → handle_format(quality_paths)                     (in-process, no stash)
  → handle_lint(quality_paths)                       (in-process, no stash)
  → real git commit --no-verify -F <msg> -- <pathspec>
  → lock released
```

### Agent commit on main

```
telec code commit --approved "chore(docs): update snippets [skip ci]"
  → commit gate satisfied (--approved present)
  → lock acquired
  → workspace scope = SHARED_BRANCH → scoped dirty paths
  → pathspec = scope minus untracked-not-staged
  → modified-tracked docs ride the pathspec unstaged
  → quality_paths = pathspec filtered to existing files
  → handle_format(quality_paths)                     (in-process, no stash)
  → handle_lint(quality_paths)                       (in-process, no stash)
  → real git commit --no-verify -F <msg> -- <pathspec>
  → lock released
```

### Agent commit with declared extras (scope heuristic missed a file)

```
telec code commit --approved "fix(scope): subject" --include path/to/extra.py
  → commit gate satisfied
  → lock acquired
  → workspace scope = SHARED_BRANCH → scoped dirty paths
  → pathspec = scope ∪ {path/to/extra.py}
  → stage extra.py only if it's untracked or unmerged
  → assert extra.py contributes a change (else error)
  → partial-staging guard runs against the merged pathspec
  → quality_paths = pathspec filtered to existing files
  → handle_format(quality_paths)
  → handle_lint(quality_paths)
  → real git commit --no-verify -F <msg> -- <pathspec>
  → lock released
```

### Integration commit

The integrator's normal home is `trees/_integration/`, which is a worktree.
Same flow as "Agent commit (worktree)" above. The integrator role bypasses
commit-first gate.

### Integrator's project-root sync

The integrator does not run `telec code commit` against the project-root main.
Repo-root sync after a delivery uses `git -C <project-root> ...` directly
(pull / merge / push). If the merge is blocked by a dirty working tree,
the integrator's main-clearance reminder reopens the check until the dirty file's owner commits via
their own session.

### Agent commit during active merge (worktree)

```
telec code commit --approved "chore(<slug>): reconcile with origin/main"
  → commit gate satisfied (--approved present)
  → lock acquired
  → wait_for_index_lock_clear

  → MERGE_HEAD detected (repo.git_dir)
  → repository root is not a declared non-project invocation context (single-owner tree)
     — otherwise the eligible set is preserved, or the commit is refused
  → assert no remaining unmerged paths (all conflicts telec code add-ed)
     — error, no commit, if any remain
  → quality_paths = full merge diff (merge-base..MERGE_HEAD), not the pathspec

  → handle_format(quality_paths)                     (in-process, no stash)
  → handle_lint(quality_paths)                        (in-process, no stash)
  → real git commit --no-verify -F <msg>              (no pathspec — full index)
  → lock released
```

## Failure modes

**Lock contention.** Another agent holds the lock. `flock(LOCK_EX)` blocks
until released. No timeout — the agent waits, no exit code.

**Empty pathspec.** `workspace scope plus --include = ∅`. The agent has
edited nothing in scope and declared no includes. Exit code 1 with guidance
pointing at `telec code changed` and the `--include <path>` recipe. There is
no silent fallback that commits the pre-staged index — committing what the
agent did not declare is precisely what the pathspec boundary prevents.

**Declared `--include` path is clean.** The agent named a file with no
changes. Exit code 2 — the agent's declaration must match reality; we don't
quietly drop unreachable claims.


**In-process gate failure.** A gate the acting tier carries fails on
`quality_paths` before `git commit --no-verify` is invoked — format or lint,
where that tier carries project subscriptions. `telec code commit` exits non-zero
with the gate output. No commit is produced; files remain in their current state
for the agent to fix and retry. A tier carrying no project subscriptions runs no
gate, so this failure mode does not arise there.


**Forgotten commit gate.** A non-integrator agent on main passes a message
without `--approved`. Exit with commit-first guidance and no commit. The agent
reruns the sealed command with `--approved`, then routes any post-commit review
obligation from the committed diff.

**Unresolved conflict during merge commit.** `MERGE_HEAD` is present and one
or more paths are still unmerged (not yet `telec code add`-ed). Exit code 1
listing the unresolved paths; no commit is produced. The agent resolves and
stages the remaining conflicts, then reruns `telec code commit`.

## See also

- docs/project/adr/0047-commit-gates-in-process-no-stash.md
- docs/global/software-development/design/workspace-scoping.md
- docs/global/software-development/policy/version-control-safety.md
- docs/project/adr/0065-integrator-parks-and-drains-with-integrity-only-gating.md — why a slug worktree's only baseline is `origin/main`: the integrator inspects and squashes against it.
