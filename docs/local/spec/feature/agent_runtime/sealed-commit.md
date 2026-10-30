---
description: 'Sealed commit interface for agent sessions inside the host pane. The git wrapper blocks raw `git add` / `git commit` and redirects to the sealed commit command, which constructs a pathspec-scoped commit from the resolved workspace scope plus declared `--include` paths. New untracked files, unmerged-index files, and partial-staged tracked files are explicitly accepted by its add command. A path enters scope by being read as well as written, so a session that reads a file another session is concurrently editing can carry that session’s uncommitted work.'
visibility: 'public'
---

# Sealed Commit — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md
- @docs/local/design/code-commit.md

## What it is

The **sealed commit contract** is the agent-facing channel for landing changes in git. Inside an agent_runtime host pane, agents do not run `git add` or `git commit` directly: the git wrapper intercepts both and redirects to `telec repo commit` (and to `telec repo add` for the rare cases git's data model genuinely requires staging). The wrapper enforces the seal at the shell level; `telec repo commit` enforces the contract internally; the final commit runs with an explicit pathspec so foreign work in the index cannot be swept in.

Ordinary raw `git add` and `git commit` invocations in a sealed repository are refused, exit non-zero, and do not stage or commit; read-only inspection such as `git diff`, `git status`, and `git log` remains available. A trusted external tool may set `TELECLAUDE_TRUSTED_TOOL=1` to step aside the wrapper entirely and execute real Git, bypassing all wrapper gates; the bypass is logged. The DeepSeek gate uses this path in its isolated home.

Within a slug worktree, an ordinary agent may not use a local `main` reference for any Git command, including read-only inspection; the wrapper refuses with a nonzero result before invoking Git and identifies `origin/main` as the baseline. The restriction applies to ref arguments before `--`, so a pathspec named `main` after `--` is unaffected. This agent rule remains distinct from the trusted external-tool path above, which bypasses the wrapper.

On the repo-root `main` branch, a push to `origin/main` is admitted only when the caller's session record resolves to the integrator role. A merge, rebase, or cherry-pick that creates a commit on `main` is blocked for non-integrator roles unless the caller uses the explicit one-shot `TELECLAUDE_OVERRIDE_APPROVED=1` replay path; that override does not apply to pushes or to `telec repo commit`.

An ordinary slug-worktree commit that includes `docs/**` or `agents/**` is refused and names each offending path and its source class, without formatting, linting, or creating a commit. The doc refusal directs the worker to the `telec todo stamp <slug> --kickback --reason <why>` route; the artifact refusal directs authorship to the main session where intent was decided. Before a pre-merge sync integrates `origin/main` into a slug worktree, dirty `agents/**` paths are refused before staging; the refusal names each path as an agent-artifact source and directs authorship to that main session, and no pre-merge sync commit is created. Repo-root `main` and the integration worktree may carry owner-authored docs and artifacts subject to the other commit gates.

The seal is scoped to invocation context roots, and which of them it covers is read from the project-subscription axis of `local/projects/teleclaude/spec/feature/config/tier-permissions`. A project root is sealed when it subscribes `code` or `docs` (`local/projects/teleclaude/spec/feature/config/project-capability-manifest`) — the same `code ∨ docs` condition as the commit obligation the seal records and evidences — and a project subscribing neither keeps ordinary git. An invocation context root whose tier carries no project subscriptions at all is sealed: it has no subscription to decide with, and the sanctioned path is its commit channel. Passthrough is decided by the repository, not by the location inside it. Where the repository's own root carries no declaration at all, the wrapper enforces nothing and execs the real git binary unmodified — the same transparent passthrough it applies outside tmux. Where the repository's root is itself a declared non-project invocation context, the seal covers the whole repository: an invocation beneath it that resolves to no context root is refused rather than passed through. A project repository is unchanged: its seal follows its subscriptions exactly as above, and every location beneath it resolves to the project's own context root.

The contract resolves four classes of file state at commit time:

1. **Modified-tracked** files in scope ride the pathspec straight from the working tree — the commit records the working-tree version, no staging needed.
2. **NEW (untracked)** files in scope are **dropped** from the pathspec unless declared via `telec repo add <path>` or `--include <path>`. This is the safety net against incidental temp/scratch artifacts the agent's tool calls may have created.
3. **Partial-staged tracked** files (staged hunks + later working-tree delta) in the pathspec are **blocked** by the partial-staging guard. The diagnostic directs the agent at `telec repo add <path>` as the recovery: it fully restages the file so the staged version matches the working tree, removing the ambiguity, after which the commit proceeds cleanly.
4. **Unmerged-index** files (post-conflict, pre-resolution-stage) in the pathspec are staged internally so the integrator's conflict-resolution flow runs through the same sealed path.

<!-- planned-change:lean-git-commit-scope -->

On a shared branch the scope itself is strictly `(live session declarations) ∩ (currently dirty paths) ∩ (the invocation context root's own material) ∩ (the repository's retained set, where its owner publishes one)`. In a linked worktree the declaration term does not apply and the scope is drawn from the worktree's dirty paths within the acting context root. Two acts declare a path: a successful `telec repo add <path>...` writes each accepted path, with the instant it was declared, to the declaring session's own declaration record, and a successful edit-tool call whose input names the file it writes is declared the same way when the runtime reports that call (`sdlc/design/workspace-scoping`). The entry stays live until the commit that carries it lands. A path named only by shell-command text contributes no evidence, and no transcript is read to establish a declaration.

A context root's **own material** is what lies under it minus what belongs to another owner. Ownership is the test, not whether TeleClaude resolves a nested root as a context: a nested root belongs to another owner when it declares a different tier, when it anchors a context of its own, or when it holds a repository of its own, and any one of those is enough. So a person's material and a company's material are both foreign to the global context that encloses them, a person-owned project is foreign to the person context that encloses it, and an unrelated checkout nested anywhere is foreign to every context above it — including the cases that anchor no context at all.

The two halves answer different failures and neither substitutes for the other. Containment under the acting root separates sessions working under _different_ context roots of one repository, so a path outside the acting root is absent from the scope whatever the transcript claims. Subtraction of foreign-owned roots excludes what sits _inside_ the acting root, which containment alone cannot reach.

The retained set is the fourth term and its membership is not this contract's to compute: where a repository's owner publishes a membership answer, that owner answers for any path with exactly one of `retained`, `not-retained`, or `outside`, and attaches no instruction to it. What the answer means here is this contract's decision: only `retained` is eligible. `not-retained` and `outside` are alike ineligible however the path is reached — the first because the owner excludes it, the second because the owner has no standing over it — and neither is ever read as permission. A repository whose owner publishes no such answer carries no such term: there is nothing to consume, this surface neither invents nor substitutes one, and the first three terms carry the bound alone. Publication and its absence are both the owner's facts, read from the owner's contract.

Containment bounds every path that reaches inspection, staging, or commit — not only the computed scope. A path named through an explicit declaration or subset channel is subject to the same bound: naming a path does not admit material outside the acting context root's own material, and such a path is refused rather than carried.
<!-- change:lean-git-commit-scope -->

On a shared branch the scope itself is strictly `(live session declarations) ∩ (currently dirty paths)`. In a linked worktree the declaration term does not apply and the scope is drawn from the worktree's dirty paths. Two acts declare a path: a successful `telec repo add <path>...` writes each accepted path, with the instant it was declared, to the declaring session's own declaration record, and a successful edit-tool call whose input names the file it writes is declared the same way when the runtime reports that call (`sdlc/design/workspace-scoping`). The entry stays live until the commit that carries it lands. A path named only by shell-command text contributes no evidence, and no transcript is read to establish a declaration.

Git stages the scope, so git's own ignore rules, repository boundary and pathspec handling decide what can be staged, and this contract keeps no second evaluation of any of them. Before committing, the contract reads what git staged: an embedded repository, staged as a gitlink entry, is refused, and so is a declared path that staged nothing. Each refusal names the path and its reason, and nothing is committed.

In the TeleClaude home a commit request records nothing of its own: `telec repo commit` runs the home snapshot (`local/projects/teleclaude/spec/feature/reconciliation/home-repository`) and reports its outcome, and `telec repo add` declares nothing there. The seal still refuses raw `git add` and `git commit` in the home.
<!-- /planned-change:lean-git-commit-scope -->

Within a single context root, and outside any nested root, the scope remains transcript-derived and a path is still touched by being read, so two sessions working the same path there are not separated by this contract; that case belongs to dirty-path ownership attribution, not to scoping.

On the repo-root `main` branch, a non-integrator agent invoking `telec repo commit` without `--approved` surfaces the **commit-first and review-routing gate** and does not commit. A bare invocation (no message) is discovery and **exits 0** — serving the gate is the successful outcome; an invocation that carries a message but omits `--approved` means the gate was forgotten and **exits non-zero**. `--approved` is the agent-owned sealed-gate acknowledgment that lets the commit proceed; it is not human approval. On a worktree or integrator role, `--approved` is still required but the gate surfacing is bypassed.

<!-- planned-change:local-operator-identity -->

A caller whose identity cannot be resolved to an agent session or verified
terminal person receives an identity-resolution diagnostic and no commit is
produced. An explicitly declared commit path that cannot be matched to
repository state is rejected before staging or commit; the diagnostic names
each invalid declaration and the whole commit is refused. If the partial-staging
gate cannot verify staged/working-tree overlap, it fails closed rather than
allowing the commit.

<!-- change:local-operator-identity -->

A caller outside any agent session for which no session, terminal login or
carried identity resolves is the computer's operator
(`local/projects/teleclaude/spec/identity-and-auth` §2): its commit is authored
by the repository's configured git identity, as a commit from a person resolved
at a terminal is. That identity names the authority the commit ran under, not
who wrote it (`general/concept/lineage-vs-authorship`). A session the platform
keeps for an operator's agent commits through the agent-session path. A caller
whose session identity document names no admissible session receives an
identity-resolution diagnostic and no commit is produced. An explicitly declared
commit path that cannot be matched to repository state is rejected before
staging or commit; the diagnostic names each invalid declaration and the whole
commit is refused. If the partial-staging gate cannot verify staged/working-tree
overlap, it fails closed rather than allowing the commit.

<!-- /planned-change:local-operator-identity -->

## Canonical fields

### Authored message boundary

The caller supplies a subject and explanatory body under
`general/policy/commits`. The commit-identity owner defines and generates platform
metadata. Caller text containing one of that owner's reserved metadata lines is
refused before commit locking, formatting, staging or Git mutation. The refusal
identifies the supported command arguments without echoing the supplied body.

Recognition covers a generated attribution line or a line beginning with a
reserved metadata key and its separator, allowing surrounding key whitespace
and case differences. It applies throughout the supplied message, rather than
only where Git would recognize a final metadata block. Ordinary prose mentioning
a key is not metadata. The shared composer enforces the same boundary for
internally generated commit messages before it adds its own metadata.

### Todo association

The optional `--todo <slug>` commit argument supplies the association described
by `general/policy/commits`. The sealed surface records the association using the
owning project's authoritative todo state. A
slug that has not been created is valid association input and creates no todo,
reservation, claim, or dispatch. Lookup failure is reported as failure to resolve
the association, rather than interpreted as proof that the todo is absent
(`sdlc/principle/design-fundamentals`).

The association records commit-time evidence; it does not track
the todo's later lifecycle or authorize work. Existing identity, human
involvement, declared-file scoping and commit-review behavior keep their own
contracts.

### Use cases

#### UC-NCR-13 — Wrapper passes through transparently in an undeclared repository

#### UC-GWR-1 — The integrator rows follow the role the caller's session record resolves to

#### UC-LMR-1 — A slug worktree cannot reference local main

#### UC-CGIP-41 — A developer learns the commit and review path on main

```gherkin
Scenario: Discover commit guidance
  Given a developer needs the commit and review route on repo-root main
  And their agent has a non-integrator role
  When the agent invokes telec repo commit without a message or flags
  Then the command provides commit-first review, scope, and next-step guidance
  And exits successfully without creating a commit
```

#### UC-CGIP-35 — telec repo add declares a modified tracked file without staging it

#### UC-CGIP-33 — A declaration is one session's path evidence across every scope consumer

#### UC-CGIP-34 — Sealed add serializes its index mutation with sealed commit

#### UC-CGIP-44 — A declaration does not depend on the shape of the command that carried it

#### UC-CGIP-1 — Commitizen format check blocks malformed message

#### UC-CGIP-2 — Format runs on quality_paths before the hook lints

#### UC-CGIP-3 — Deletion-only commit bypasses format/lint

#### UC-CGIP-4 — Clean commit passes through the pre-commit hook

#### UC-CGIP-5 — Format failure blocks commit

#### UC-CGIP-6 — Lint failure blocks commit

#### UC-CGIP-48 — A repository's first commit passes through the same gates

#### UC-CGIP-7 — Lock releases cleanly on gate failure

#### UC-CGIP-8 — Bare commit surfaces the gate and exits 0

#### UC-CGIP-9 — Message without --approved is a forgotten gate

#### UC-CGIP-45 — The gate card carries the diffstat of the scope it would commit

#### UC-CGIP-10 — A developer can integrate upstream changes in a worktree

```gherkin
Scenario: Commit a resolved upstream merge
  Given a developer asks their agent to merge origin/main into a single-owner worktree
  And all merge conflicts are resolved
  When the agent commits the merge
  Then the complete merge result is committed
  And all incoming changes receive the applicable checks
  And origin/main remains a parent of the merge commit

Scenario: Refuse a merge with unresolved conflicts
  Given the merge still has unresolved paths
  When the developer's agent attempts to commit it
  Then the refusal names the unresolved paths
  And no commit is created
```

#### UC-CGIP-11 — Unresolved conflict during merge commit is rejected

#### UC-CGIP-12 — Slug worktree refuses doc-layer paths

#### UC-CGIP-13 — Main branch and integration worktree are unaffected by the doc refusal

#### UC-CGIP-12a — Slug worktree refuses agent-artifact source paths

#### UC-CGIP-13a — Main branch and integration worktree are unaffected by the agent-artifact refusal

#### UC-CGIP-29 — The pre-merge worktree sync refuses agent-artifact source paths

#### UC-CGIP-14 — An unresolvable transcript neither errors nor withdraws the session's declarations

#### UC-CGIP-15 — Sealed commit stamps the agent's author identity and appends the session trailer

#### UC-CGIP-17 — A person the platform resolves at a terminal degrades honestly to the human as author

```
Given a telec repo commit invocation from outside any agent session
And the platform resolves the invoking caller as a registered person from their terminal login
When the commit lands
Then git's own ambient identity resolves the author
And the message carries no Session: trailer
```

<!-- planned-change:local-operator-identity -->

#### UC-CGIP-18 — A caller the platform cannot identify fails the commit loudly

<!-- change:local-operator-identity -->

#### UC-CGIP-18 — A caller whose session identity names no admissible session fails the commit loudly

<!-- /planned-change:local-operator-identity -->

#### UC-CGIP-47 — Commit attribution resolves from the carried identity

#### UC-CGIP-16 — Human-Involved is a per-commit declaration, never derived from the todo record

#### UC-CGIP-19 — Human-Involved defaults to false when no declaration is made

#### UC-CGIP-20 — Human-Involved is true when the committing session's observed human input is recent

#### UC-CGIP-38 — Human involvement requires a non-empty invocation reason

#### UC-CGIP-39 — Stale human activity records false and the commit lands

#### UC-CGIP-42 — A discarded commit declaration is observable with its age

#### UC-CGIP-43 — An unreachable session store records false rather than failing the commit

#### UC-CGIP-40 — Human involvement never propagates between commits

#### UC-CGIP-21 — A pre-existing tool-shaped line in the message is left untouched, not enforced against

#### UC-CGIP-24 — The integrator's worktree-cleanup commit carries the full footer

#### UC-CGIP-25 — The pre-merge worktree sync commit carries the full footer

#### UC-CGIP-32 — A declared path the repository cannot match is refused before git runs

#### UC-NCR-1 — Change inspection from a context root below the repository root

<!-- planned-change:lean-git-commit-scope -->

#### UC-NCR-2 — A commit from a nested context root lands only that context's changes

#### UC-NCR-3 — Concurrent work elsewhere in the same history is untouched

#### UC-NCR-4 — A foreign nested root is not carried

#### UC-NCR-5 — A developer can inspect what a commit will carry

```gherkin
Scenario: Review the scope summary at the main-branch gate
  Given a developer is preparing a commit on main through a non-integrator agent
  When the commit-first gate card appears
  Then it shows a per-file diffstat of the resolved commit scope against HEAD
  And identifies when the scope is empty
  And if the scope cannot be resolved, directs the agent to inspect the diff

Scenario: Preview the exact payload from a nested context
  Given a developer's agent works from a context nested below the repository root
  And the developer wants to see what their explicit commit will carry
  When the agent previews the eligible scope
  Then the exact paths are shown in that context's coordinates
  And paths owned by another context or excluded by the repository owner are absent
```

#### UC-NCR-6 — Containment outranks the session's own path set

#### UC-NCR-7 — The seal holds at an invocation context root that is not a project

#### UC-NCR-8 — An invocation context carrying neither subscriptions nor a participating surface commits with no gates and no substitute

#### UC-NCR-14 — A home declaring no capabilities gets only the documentation checks

#### UC-NCR-15 — A tier carrying code still requires its native toolchain

#### UC-NCR-9 — A context root that is also the repository root is unchanged

#### UC-NCR-10 — A declared path outside the acting context's own material is refused

#### UC-NCR-12 — A commit taken mid-merge does not escape the bound

<!-- change:lean-git-commit-scope -->

#### UC-NCR-5 — A developer can inspect what a commit will carry

```gherkin
Scenario: Review the scope summary at the main-branch gate
  Given a developer is preparing a commit on main through a non-integrator agent
  When the commit-first gate card appears
  Then it shows a per-file diffstat of the resolved commit scope against HEAD
  And identifies when the scope is empty
  And if the scope cannot be resolved, directs the agent to inspect the diff
```

#### UC-NCR-7 — The seal holds at an invocation context root that is not a project

#### UC-NCR-8 — An invocation context carrying neither subscriptions nor a participating surface commits with no gates and no substitute

#### UC-NCR-14 — A home declaring no capabilities gets only the documentation checks

#### UC-NCR-15 — A tier carrying code still requires its native toolchain

#### UC-NCR-9 — A context root that is also the repository root is unchanged

#### UC-NCR-16 — A commit requested in the home records the home's snapshot

#### UC-NCR-17 — An embedded repository is refused by name

<!-- /planned-change:lean-git-commit-scope -->

#### UC-NCR-11 — A location with no context root inside a sealed repository cannot reach raw git

#### UC-TH-1 — Thin hook partial-staging backstop

#### UC-TH-2 — The hook passes clean commits

#### UC-TH-3 — Thin hook fails closed on git status probe failure

#### UC-TH-4 — A raw git commit and telec repo commit get the same verdict

#### UC-TH-5 — Another session's uncommitted file does not decide a commit

#### UC-TH-6 — A context without code is still gated for its documentation

#### UC-TH-7 — The hook checks formatting and never rewrites a file

#### UC-TH-8 — A merge commit git creates on its own passes the same gate

#### UC-CGIP-49 — A file written through an edit tool is committed without an explicit declaration

#### UC-CGIP-50 — A commit in a todo worktree publishes the todo's branch

```
Given a developer wants a task commit available from the project's remote
When their agent commits the task change in that todo's worktree
Then the todo's branch is published to the project's origin
```

#### UC-CGIP-51 — A failed publication leaves the commit in place

#### UC-CGIP-52 — Rewritten branch history replaces the published branch

#### UC-CGIP-53 — Remote work the worktree has never seen is not overwritten

#### UC-CGIP-54 — Main and the integration worktree publish nothing

#### UC-CGIP-55 — A project without an origin remote commits as before

#### UC-CGIP-56 — A worktree checked out on another branch publishes nothing

<!-- planned:local-operator-identity -->

#### UC-CGIP-57 — The computer's operator commits under the repository's git identity

```gherkin
Given an agent another application started, outside any agent session
And no session, terminal login or carried identity names a person for it
When it commits through telec repo commit
Then the commit lands authored by the repository's configured git identity
```

#### UC-CGIP-58 — An operator's headless session commits as an agent session

```gherkin
Given a session the platform keeps for an agent it did not launch, under the computer's operator
When the agent commits through telec repo commit inside that session
Then the commit lands with the same scope and gates as any agent session's commit
```

<!-- /planned:local-operator-identity -->

## See also

- docs/local/design/code-commit.md
- docs/global/sdlc/policy/version-control-safety.md
