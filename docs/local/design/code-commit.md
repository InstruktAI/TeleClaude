---
description: 'Design of the canonical agent commit command with workspace-scope staging and pathspec-scoped commits.'
visibility: 'public'
---

# Code Commit — Design

## Required reads

@~/.teleclaude/docs/general/policy/commits.md

## Purpose

`telec repo commit` is the canonical commit interface for **autonomous agent
sessions inside tmux**. It resolves the workspace scope and runs `git commit`
with an explicit pathspec.

The staging model is asymmetric and follows git's data model:

- **Modified-tracked files in scope** that are NOT partial-staged ride the
  pathspec straight from the working tree — `git commit -- <path>` records
  the working-tree version, no staging needed. When a shell command wrote the
  file, `telec repo add <path>` declares it into session scope while leaving
  its index state unchanged.
- **Partial-staged tracked files** in the commit pathspec (staged hunks +
  later working-tree delta) are BLOCKED by the partial-staging guard —
  `git commit -- <path>` would otherwise sweep unstaged hunks the agent
  did not declare into the commit. The blocking diagnostic points the
  agent at the recovery: `telec repo add <path>` fully restages the file
  so the staged version matches the working tree, eliminating the
  ambiguity, after which `telec repo commit` proceeds cleanly.
- **NEW (untracked) files in scope** are NOT auto-committed. The agent must
  declare them via `telec repo add <path>` (sealed equivalent of `git add`)
  or `--include <path>` at commit time. This is the safety net against
  incidental temp/scratch artifacts the agent's tool calls may have created.
- **Unmerged-index files in pathspec** (post-conflict, pre-resolution-stage)
  are staged internally via `_stage_files` so the integrator's conflict
  resolution flow runs through the same sealed path.

`telec repo commit` formats `quality_paths` (the commit pathspec filtered to
existing files), then runs `git commit`, which runs the installed
`.git/hooks/pre-commit`. The hook applies to each staged path the gates its
owning home's declared tier carries, so every route into a commit, a raw
`git commit` included, passes the same gate.

**Whether** the gate runs follows the tier: a tier carrying project
subscriptions, or whose material participates in documentation, is gated. A tier
carrying neither is not, and nothing is applied in its place.

**Which checks run** follows what the tier carries, never where its root sits.
The project's native toolchain leg runs where the tier carries `code`.
TeleClaude's guardrails lane runs wherever the gate runs. A tier carrying both
runs both after staged-content preparation; the read-only legs may overlap,
with bounded concurrency and deterministic failure selection under
`local/projects/teleclaude/spec/feature/agent_runtime/quality-runner-process-groups`.

The platform home, and the person and company homes inside it, participate in
documentation and carry no project subscriptions. They are gated, they run the
guardrails lane, and they require no native toolchain contract at their root —
by no separate mechanism.
No framework stash, no working-tree reset
outside the pathspec. The hook applies the partial-staging guard first. The
documentation and agent-artifact validators then grade the staged files against
the rest of each owning home as committed, never against another session's
uncommitted files; the native toolchain leg runs on disk over the staged files,
which the partial-staging guard makes identical to what is staged. The hook
checks formatting and never rewrites a file.

The git wrapper redirects raw `git commit` (and `git add`) to this command
for tmux callers.

**Caller paths:**

A commit reaches git through one of four contexts in this repository: the human
shell outside tmux, an autonomous agent inside tmux within a telec-registered
project, an agent inside tmux within a repository whose own root is a declared
invocation context that is not a project, and an agent inside tmux operating in a
repository whose own root carries no declaration.

| Caller context                                  | Command                            | Why telec is or isn't involved                                                                                                                     |
| ----------------------------------------------- | ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Outside tmux (human shell)                      | `git commit ...`                   | The wrapper passes through to real git directly when `$TMUX` is unset. No identity check, no env var, no telec.                                    |
| Inside tmux, autonomous agent (registered)      | `telec repo commit --approved ...` | Lock + workspace scope + pathspec commit. The body of this design.                                                                                 |
| Inside tmux, repository root a declared context | `telec repo commit --approved ...` | Sealed on the repository's own declaration rather than on project subscriptions; an invocation beneath it resolving to no context root is refused. |
| Inside tmux, repository root undeclared         | `git commit ...`                   | The repository's own root carries no declaration → the wrapper enforces nothing and execs real git unmodified, as it does outside tmux.            |

Inside tmux there is **no env-var bypass on `git commit`**. The wrapper
redirects every `git commit` invocation to `telec repo commit` with no
override. `--include` is the only way to extend the commit pathspec beyond
the resolved workspace scope, and the agent must name every path it claims.

**Wrapper-enforced intent layer:**

The git wrapper enforces the intent layer for every git invocation in a
tmux session. `telec repo commit` runs on top of these guarantees.

Every row below presupposes the git invocation targets a sealed repository. A
telec-registered project that subscribes `code` or `docs` — a working tree under
a checkout carrying `teleclaude.yml` whose manifest subscribes at least one of
`code` or `docs` (`local/projects/teleclaude/spec/feature/config/project-capability-manifest`) — is
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

The wrapper takes capability state from the runtime's answer for the repository
root's own `teleclaude.yml`, deriving `code ∨ docs` for commit interception and
`code` for worktree and branch discipline. The wrapper reads no declaration
itself. The runtime answers: the document is brought to its current shape by the configuration migration list,
environment references in its capability blocks are resolved from the
declaration's sibling `.env`, and its tier and capability blocks are read with
the runtime's own models. The wrapper keeps that answer until a file it was
read from changes or the installation's code advances, so a read after either
starts an interpreter and later reads reuse the kept answer; the whole-second
limit on keeping an answer is stated with the contract (`local/projects/teleclaude/spec/feature/config/project-capability-manifest`). A
project declaration carries the capability blocks: a block that is absent, or
present without an `enabled` value, leaves that capability unsubscribed. A
global or person declaration carries no subscriptions: the repository is sealed
on the declaration alone, so the commit-interception rows and the main-branch
replay and push rows apply there, while the worktree and destructive-operation
rows follow `code`, which no non-project tier carries. A company declaration
anchors no context and seals nothing: the wrapper execs the real git binary
unmodified.

A declaration the wrapper cannot resolve — no readable tier, a capability block
the runtime cannot read, or a runtime that cannot answer — refuses the git
invocation with a message naming `teleclaude.yml` and the cause, and
substitutes no capability state. The wrapper and the runtime's capability
answer both read only the tier and the capability blocks, so they answer alike
for every declaration; a declaration that fails validation elsewhere in the
overlay is refused only where the full overlay is loaded
(`local/projects/teleclaude/spec/feature/config/project-capability-manifest`).

The role the matrix reads is resolved from the caller's session record through the
shared caller resolution (`local/projects/teleclaude/spec/identity-and-auth` §6), never from the
session identity document, which carries only the session id
(`local/projects/teleclaude/spec/feature/identity/session-identity-file`). The wrapper resolves it
only where a row depends on role: a push to main, and a replay that produces a
commit on main.

The full matrix of wrapper-gated operations, by role and by execution
context. Read columns left-to-right; the first column that decides the
op wins.

| Operation                                                                     | Worker (worktree or repo root) | Integrator (in `trees/_integration/`) | Active merge (`MERGE_HEAD` present) | Rationale             |
| ----------------------------------------------------------------------------- | ------------------------------ | ------------------------------------- | ----------------------------------- | --------------------- |
| `git status`, `git log`, `git show`, `git diff <ref>..<ref>`, `git rev-parse` | ✅ allowed                     | ✅ allowed                            | ✅ allowed                          | Read-only inspection. |

| `git add` (any form) | ❌ blocked → `telec repo add` | ❌ blocked → `telec repo add` | ❌ blocked → `telec repo add` | Staging is telec's job; sealed-commit pathspec depends on it. Also the resolved-conflict recovery path during an active merge. |

| `git commit` | ❌ blocked → `telec repo commit` | ❌ blocked → `telec repo commit` | ⚠️ `telec repo commit` (full commit, no pathspec — single-owner trees only) | Sealed commit contract; no env-var bypass. Mid-merge, git refuses any pathspec-scoped commit (`fatal: cannot do a partial commit during a merge`) regardless of pathspec completeness, so in a single-owner tree `telec repo commit` degrades to a full-index commit, which carries only that one owner's resolved state. In a repository whose own root is a declared non-project invocation context the tree has more than one owner, and there the commit preserves the eligible set or is refused; it never degrades to the whole index. An ordinary project checkout is a single-owner tree and keeps this row's existing behavior unchanged. |

| `git reset HEAD <path>` / `git reset -- <path>` (pathspec) | ✅ allowed | ✅ allowed | ✅ allowed | Path-scoped unstage; index-only effect. |
| `git reset` (no pathspec) | ❌ blocked | ❌ blocked | ❌ blocked | Discards staged state non-locally. |
| `git reset --hard\|--merge\|--keep` | ❌ blocked | ❌ blocked | ❌ blocked | Discards commits / merge state. |
| `git restore <path>` (working-tree revert to HEAD) | ✅ allowed | ⚠️ `--confirmed` required | ⚠️ `--confirmed` required | Same risk as `git checkout HEAD -- <path>`. Worktree-only blast radius elsewhere; in the integration worktree the working tree feeds DELIVERY_BOOKKEEPING. |
| `git restore --staged <path>` | ✅ allowed | ✅ allowed | ✅ allowed | Index-only effect; same as `git reset -- <path>`. |
| `git restore --source <ref> <path>` | ✅ allowed | ⚠️ `--confirmed` required | ⚠️ `--confirmed` required | Pulls foreign content from `<ref>` into working tree; same risk surface as `git checkout <ref> -- <path>`. |
| `git checkout -- <path>` (no ref) | ✅ allowed | ⚠️ `--confirmed` required | ⚠️ `--confirmed` required | Working-tree revert to HEAD; same gating as `git restore <path>`. |
| `git checkout <ref> -- <path>` | ✅ allowed | ⚠️ `--confirmed` required | ⚠️ `--confirmed` required | Foreign-ref content into working tree. |
| `git checkout <branch>` / `git switch` | ❌ blocked | ❌ blocked | ❌ blocked | Branch switching loses workspace; not how agents change branches. |
| `git stash*` | ❌ blocked (absolute, no role override) | ❌ blocked | ❌ blocked | In a multi-agent repo, a stash lifts working-tree changes out of the checkout that other agents may own; the pop either silently re-stages foreign content or conflicts with no clean recovery. The integrator resolves dirty files that block repo-root sync path by path under the integration procedure — it asks the sessions that can have written each path and commits a quiet, unclaimed path as-is — and never stashes. |
| `git clean` | ❌ blocked | ❌ blocked | ❌ blocked | Deletes untracked files; rarely the right answer for agents. |
| `git revert <commit>` | ⚠️ `--confirmed` required | ⚠️ `--confirmed` required | ⚠️ `--confirmed` required | Multi-agent commits often span scopes; inspection precedes revert. |
| `git merge`/`rebase`/`cherry-pick` on main | ❌ unless integrator role or `TELECLAUDE_OVERRIDE_APPROVED=1` | ✅ allowed | (n/a) | Replays produce commits via paths that bypass `telec repo commit`'s sealed commit gate. |
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

**Wrapper stash rule:** For code-capable checkouts, `rebase.autoStash`,
`merge.autoStash`, and `pull.autoStash` are forced off. An explicit
`--autostash` argument (including Git's accepted abbreviations), per-command
autoStash config overrides, per-command config includes, and inherited
autoStash or include parameters are refused before Git runs;
`--no-autostash` remains allowed. A managed session refuses a malformed
inherited `GIT_CONFIG_COUNT` before choosing a repository.
`git add -A`/`git add --all`/`git add .` are blocked on main for
non-integrators regardless of the table above — staging on main always
names files explicitly.

## Inputs / Outputs

The arguments below compose with the optional todo association owned by
`local/projects/teleclaude/spec/feature/agent_runtime/sealed-commit`; its
association follows `general/policy/commits`.

- `"<message>"` — one quoted commit message (required when `--approved`).
- `--approved` — agent-owned sealed-gate acknowledgment. Absence triggers
  commit-first and post-commit review-routing guidance; it is not a human
  approval signal.
- `--human-involved <reason>` — an action-scoped audit declaration requiring a
  non-empty reason. The recorded value is resolved in this process from the
  acting session's latest authenticated human input against the code-owned
  recency window; input outside the window, an unresolvable session, and an
  unreadable session store all record `false` and leave the commit otherwise
  unchanged. The reason is consumed for invocation validation and remains only
  in the invoking session transcript; the commit carries only the existing
  boolean footer.
- `--include <path> [<path> ...]` — declare files outside the resolved
  workspace scope that must be in this commit (e.g., a file the human
  collaboratively edited that the scope heuristic missed). Each declared
  path must contribute a change; clean paths are rejected.

Nothing is forwarded to git: no `-m`, no `-F`, no `--`, no bare pathspecs.
The pathspec commit is built internally from `workspace scope plus
--include paths`.

**Outputs:** committed changeset, or failure with actionable diagnostics. In a
todo worktree, a successful commit also publishes the todo's branch to
`origin` and reports a publication failure alongside the recorded commit
(Invariant 13).

## Invariants

1. **Lock serialisation.** `main_branch_lock()` (flock on
   `GIT_MAIN_LOCK_PATH`) serialises commit execution and the staging mutation
   performed by `telec repo add`. Both paths call
   `wait_for_index_lock_clear()` while holding that lock before writing the
   index. The lock auto-releases on process exit or crash.

   Stale `.git/index.lock` self-heal uses the existing bounded holder and age
   checks before removal. The flock and Git's index lock remain distinct; the
   wait protects both operations from a prior Git process killed mid-write.

2. **Workspace scope is authoritative — for pathspec construction, not staging.**
   `resolve_workspace_scope_resolution()` is the single owner of
   worktree-vs-shared-branch scope. The scope set drives the commit's
   pathspec (with `--include` adding explicit, agent-declared paths and
   untracked-not-staged files dropped); it does **not** drive staging.
   Staging is a narrow follow-up step that runs only on the three cases
   git's data model genuinely requires it for: untracked files in the
   pathspec, unmerged-index files in the pathspec, and partial-staged
   tracked files (handled via `telec repo add` recovery). Modified-tracked
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

4. **The pre-commit hook runs the checks each staged path's owning home carries.**
   Whether the gate runs, and which checks it runs, follow the owning home of
   each staged path, never the directory the commit started from, under the
   capability rule in
   `local/projects/teleclaude/spec/feature/config/project-capability-manifest`: the
   gate runs where that home carries `code` or `docs`, a global, person, or
   company home counting as `docs` and `agents` by its kind, and each capability contributes
   only its own checks — `code` the native toolchain and TeleClaude's code
   rules, `docs` snippet validation, `agents` artifact validation. A home
   carrying neither is not gated, and nothing is applied in its place. The
   checks run from `.git/hooks/pre-commit` (`telec repo pre-commit`) against
   the commit's staged file set, after the partial-staging guard. Formatting is
   checked, never rewritten. The documentation and agent-artifact validators
   read the staged content against the rest of each owning home as committed;
   the native leg runs on disk over the staged files. `telec repo commit`
   formats `quality_paths` (the commit pathspec filtered to existing files)
   before staging and passes no `--no-verify`, so its commits pass the same
   hook as a raw `git commit`. A home without `code` requires no native
   toolchain contract at its root. The selected checks run in-process when the
   checkout under commit is the installation or is not a TeleClaude checkout.
   For any other TeleClaude checkout exactly the selected checks run in that
   checkout's own code — a slug worktree against the worktree's home
   (`local/projects/teleclaude/spec/feature/agent_runtime/isolated-home`), any other checkout
   against a fresh scratch home — so a change is graded by the rules it carries
   and undelivered code never runs against the live home; a checkout that cannot
   run the selected checks in its own code, or a slug worktree whose home is
   missing, is refused rather than graded by installed rules
   (`local/projects/teleclaude/design/architecture/cli-invocation-boundary`).
   Deletion-only commits
   (empty `quality_paths`) skip formatting and the native leg; the documentation
   and agent-artifact validators still grade each owning home of a deleted path.
   In TeleClaude's own repository the gate also runs the cold acceptance profile
   when a staged path — added, changed or deleted — lies outside documentation
   and standalone prose, the same classification the code-scoped review latch
   reads (`local/projects/teleclaude/spec/feature/agent_runtime/runtime-acceptance`).

5. **Commit-first gate on main.** Non-integrator agents on main use the bare
   `telec repo commit` invocation to surface commit-first and post-commit
   review-routing guidance. They then commit with `--approved`; the committed
   diff determines whether a post-commit review is required or recommended per
   `general/policy/commits`. This design owns the mechanics; the
   policy owns the behavioral rule.

6. **Orchestrator restriction.** Orchestrators cannot commit on any branch.

7. **Wrapper redirect.** The git wrapper blocks `git commit` and directs agents
   to `telec repo commit`. The wrapper retains all other safety blocks
   (stash, checkout, restore, clean, reset, push on main).

8. **Real git bypass for the inner commit.** The final `git commit` call uses
   the real git binary (via GitPython) so the wrapper's redirect does not loop
   back into telec; git still runs the installed hooks.

<!-- planned-change:lean-git-commit-scope -->

9. **`MERGE_HEAD`-aware commit degrades the pathspec boundary where the tree has
   one owner.** When `MERGE_HEAD` is present (resolved via `repo.git_dir`, not a
   literal `.git/` path, so this holds inside worktrees), git categorically
   refuses a pathspec-scoped commit during an active merge, independent of
   whether the pathspec happens to cover the entire resolved index. In a
   single-owner tree — a worker's own worktree, the integration worktree, a
   project checkout — Invariant 3's pathspec boundary therefore does not apply:
   `telec repo commit` requires every unmerged path already resolved
   (`telec repo add`-ed) — it errors out listing any that remain rather than
   committing an unresolved conflict — then commits with no pathspec at all:
   `git commit -F <msg>` with no trailing `-- <pathspec>`. The hook grades the
   full staged merge result, not the caller's pathspec.

   In a repository whose own root is a declared non-project
   invocation context the tree has more than one owner: such a tree is multi-context and concurrently dirty by design, so the
   resolved index can hold another context's material. There a commit taken mid-
   merge preserves the eligible set or is refused; it never degrades to recording
   the whole index.

10. **Two roots resolve as a pair, once, at the entry points.** Every
    `telec repo` verb resolves the invocation context root (the nearest
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
    declared path (`--include`, `--only`, `telec repo add`) alike; a declared
    path outside it is refused, never carried. The retained-set term consumes
    the reconciliation context's published membership answer where one is
    published — a three-result answer per path, of which only `retained`
    admits, `not-retained` and `outside` alike excluding; a repository whose
    owner publishes none carries no such term, and this surface neither
    decides membership nor substitutes an answer in either case.

<!-- change:lean-git-commit-scope -->

9. **`MERGE_HEAD`-aware commit degrades the pathspec boundary where the tree has
   one owner.** When `MERGE_HEAD` is present (resolved via `repo.git_dir`, not a
   literal `.git/` path, so this holds inside worktrees), git categorically
   refuses a pathspec-scoped commit during an active merge, independent of
   whether the pathspec happens to cover the entire resolved index. In a
   single-owner tree — a worker's own worktree, the integration worktree, a
   project checkout — Invariant 3's pathspec boundary therefore does not apply:
   `telec repo commit` requires every unmerged path already resolved
   (`telec repo add`-ed) — it errors out listing any that remain rather than
   committing an unresolved conflict — then commits with no pathspec at all:
   `git commit -F <msg>` with no trailing `-- <pathspec>`. The hook grades the
   full staged merge result, not the caller's pathspec.

10. **Two roots resolve as a pair, once, at the entry points.** Every
    `telec repo` verb resolves the invocation context root (the nearest
    declaration above the invocation directory) and the repository root (the
    nearest git checkout above it) as distinct coordinates and threads both to
    everything downstream. The repository root anchors git operations and the
    paths git reports; the invocation context root anchors permission (its
    declared tier's answers, read from the config context's tier-permission
    contract) and the coordinates in
    which answers are expressed. Where the two coincide — every project
    checkout — the pair degenerates to the single root and nothing observable
    changes.

11. **Git bounds what a commit carries.** The scope is staged through git,
    whose ignore rules, repository boundary and pathspec handling apply
    unchanged; this surface keeps no second evaluation of any of them. Before
    committing it reads what git staged and refuses an embedded repository (a
    gitlink entry) and a declared path that staged nothing, naming each path and
    its reason. In the TeleClaude home a commit request runs the home snapshot
    instead of a scoped commit
    (`local/projects/teleclaude/design/architecture/home-repository`).

<!-- /planned-change:lean-git-commit-scope -->

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

13. **A todo worktree's commit publishes its branch after the commit is
    recorded.** In a slug worktree (`trees/<slug>`, never `trees/_integration`)
    of a repository with an `origin` remote, a successful commit is followed by
    a push of the todo's branch — the branch named after the worktree — to the
    same-named branch on `origin`, and only when that branch is the one checked
    out; any other checked-out branch is reported unpublished and never pushed. The
    push runs after the lock of Invariant 1 is released, so no other session's
    commit waits on the network. It is a lease-guarded forced update that also
    requires the remote-tracking tip to be reachable from the local branch's
    own history: history the worktree rewrote replaces the published branch,
    and commits on `origin` the worktree never integrated are refused rather
    than overwritten (`sdlc/policy/version-control-safety`). The commit
    is final before publication begins: a rejected, failed, or timed-out push
    changes neither the commit nor the command's exit status; it is reported
    with git's own reason, and the next commit publishes again. Main, the
    integration worktree, and a repository without `origin` publish nothing,
    and the last says nothing about it.

## Primary flows

Every walkthrough below traces an acting context whose declared tier carries project subscriptions, so its gate steps are the ones that tier carries. In a context whose tier carries none, the same flows run with no gate step at all.

### Agent commit (worktree)

```
telec repo commit --approved "feat(scope): subject"
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
  → handle_format(quality_paths)                     (before staging, no stash)
  → real git commit -F <msg> -- <pathspec>
    → .git/hooks/pre-commit → telec repo pre-commit
      → partial-staging guard
      → lint the staged file set (format checked, never rewritten)
  → lock released
  → slug worktree with an origin remote → publish the branch (Invariant 13)
    → success: done
    → failure: report git's reason; the commit stands; exit status unchanged
```

### Agent commit on main

```
telec repo commit --approved "chore(docs): update snippets [skip ci]"
  → commit gate satisfied (--approved present)
  → lock acquired
  → workspace scope = SHARED_BRANCH → scoped dirty paths
  → pathspec = scope minus untracked-not-staged
  → modified-tracked docs ride the pathspec unstaged
  → quality_paths = pathspec filtered to existing files
  → handle_format(quality_paths)                     (before staging, no stash)
  → real git commit -F <msg> -- <pathspec>
    → .git/hooks/pre-commit → telec repo pre-commit (same gate as raw git commit)
  → lock released
```

### Agent commit with declared extras (scope heuristic missed a file)

```
telec repo commit --approved "fix(scope): subject" --include path/to/extra.py
  → commit gate satisfied
  → lock acquired
  → workspace scope = SHARED_BRANCH → scoped dirty paths
  → pathspec = scope ∪ {path/to/extra.py}
  → stage extra.py only if it's untracked or unmerged
  → assert extra.py contributes a change (else error)
  → partial-staging guard runs against the merged pathspec
  → quality_paths = pathspec filtered to existing files
  → handle_format(quality_paths)
  → real git commit -F <msg> -- <pathspec>
    → .git/hooks/pre-commit → telec repo pre-commit
  → lock released
```

### Integration commit

The integrator's normal home is `trees/_integration/`, which is a worktree.
Same flow as "Agent commit (worktree)" above. The integrator role bypasses
commit-first gate.

### Integrator's project-root sync

Repo-root sync after a delivery uses `git -C <project-root> ...` directly
(pull / merge / push). If the merge is blocked by a dirty working tree, the
integrator's main-clearance reminder reopens the check on each beat and resolves
each dirty path under `sdlc/procedure/lifecycle/integrate`: it asks the sessions
that can have written the path, and commits a quiet, unclaimed path as-is with a
pathspec-scoped `telec repo commit`.

### Agent commit during active merge (worktree)

```
telec repo commit --approved "chore(<slug>): reconcile with origin/main"
  → commit gate satisfied (--approved present)
  → lock acquired
  → wait_for_index_lock_clear

  → MERGE_HEAD detected (repo.git_dir)
  → repository root is not a declared non-project invocation context (single-owner tree)
     — otherwise the eligible set is preserved, or the commit is refused
  → assert no remaining unmerged paths (all conflicts telec repo add-ed)
     — error, no commit, if any remain
  → quality_paths = full merge diff (merge-base..MERGE_HEAD), not the pathspec

  → handle_format(quality_paths)                     (before committing, no stash)
  → real git commit -F <msg>                          (no pathspec — full index)
    → .git/hooks/pre-commit → telec repo pre-commit over the full staged index
  → lock released
```

## Failure modes

**Lock contention.** Another agent holds the lock. `flock(LOCK_EX)` blocks
until released. No timeout — the agent waits, no exit code.

**Empty pathspec.** `workspace scope plus --include = ∅`. The agent has
edited nothing in scope and declared no includes. Exit code 1 with guidance
pointing at `telec repo add <path>` and the `--include <path>` recipe. There is
no silent fallback that commits the pre-staged index — committing what the
agent did not declare is precisely what the pathspec boundary prevents.

**Declared `--include` path is clean.** The agent named a file with no
changes. Exit code 2 — the agent's declaration must match reality; we don't
quietly drop unreachable claims.

**Hook gate failure.** A gate the acting tier carries fails on the staged file
set inside `.git/hooks/pre-commit`, whichever route started the commit. git
aborts the commit, and the hook output names each finding; an unformatted file
is named with the format command that fixes it. No commit is produced; files
remain in their current state for the author to fix and retry. A tier that
carries no gate runs none, so this failure mode does not arise there.

**Forgotten commit gate.** A non-integrator agent on main passes a message
without `--approved`. Exit with commit-first guidance and no commit. The agent
reruns the sealed command with `--approved`, then routes any post-commit review
obligation from the committed diff.

**Unresolved conflict during merge commit.** `MERGE_HEAD` is present and one
or more paths are still unmerged (not yet `telec repo add`-ed). Exit code 1
listing the unresolved paths; no commit is produced. The agent resolves and
stages the remaining conflicts, then reruns `telec repo commit`.

**Branch publication fails.** The commit is already recorded when the push of
Invariant 13 is rejected, fails in transport, or times out. `telec repo commit`
exits with the commit's own status, prints that publishing the branch to
`origin` failed with git's reason, and states that the commit stands and the
next commit publishes again. A refusal because `origin` holds commits the
worktree never integrated repeats on every commit until the branch
integrates them; the report names that reason each time.

## See also

- docs/local/adr/0108-the-git-pre-commit-hook-is-the-only-commit-gate.md
- docs/global/sdlc/design/workspace-scoping.md
- docs/global/sdlc/policy/version-control-safety.md
- docs/local/adr/0065-integrator-parks-and-drains-with-integrity-only-gating.md — why a slug worktree's only baseline is `origin/main`: the integrator inspects and squashes against it.
- docs/local/adr/0097-involvement-is-observed-not-adjudicated.md — why the involvement record is resolved from observed presence and never refuses the commit.
