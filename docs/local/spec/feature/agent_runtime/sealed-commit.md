---
description: 'Sealed commit interface for agent sessions inside the host pane. The git wrapper blocks raw `git add` / `git commit` and redirects to `telec code commit`, which constructs a pathspec-scoped commit from the resolved workspace scope plus declared `--include` paths. New untracked files, unmerged-index files, and partial-staged tracked files are explicitly accepted by `telec code add`. A path enters scope by being read as well as written, so a session that reads a file another session is concurrently editing can carry that session’s uncommitted work.'
visibility: 'public'
---

# Sealed Commit — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md
- @docs/local/design/code-commit.md

## What it is

The **sealed commit contract** is the agent-facing channel for landing changes in git. Inside an agent_runtime host pane, agents do not run `git add` or `git commit` directly: the git wrapper intercepts both and redirects to `telec code commit` (and to `telec code add` for the rare cases git's data model genuinely requires staging). The wrapper enforces the seal at the shell level; `telec code commit` enforces the contract internally; the final commit runs with an explicit pathspec so foreign work in the index cannot be swept in.

Ordinary raw `git add` and `git commit` invocations in a sealed repository are refused, exit non-zero, and do not stage or commit; read-only inspection such as `git diff`, `git status`, and `git log` remains available. A trusted external tool may set `TELECLAUDE_TRUSTED_TOOL=1` to step aside the wrapper entirely and execute real Git, bypassing all wrapper gates; the bypass is logged. The DeepSeek gate uses this path in its isolated home.

Within a slug worktree, an ordinary agent may not use a local `main` reference for any Git command, including read-only inspection; refusal identifies `origin/main` as the baseline. The restriction applies to ref arguments before `--`, so a pathspec named `main` after `--` is unaffected. This agent rule remains distinct from the trusted external-tool path above, which bypasses the wrapper.

The seal is scoped to invocation context roots, and which of them it covers is read from the project-subscription axis of `local/projects/teleclaude/spec/feature/config/tier-permissions`. A project root is sealed when it subscribes `code` or `docs` (`local/projects/teleclaude/spec/feature/config/project-capability-manifest`) — the same `code ∨ docs` condition as the commit obligation the seal records and evidences — and a project subscribing neither keeps ordinary git. An invocation context root whose tier carries no project subscriptions at all is sealed: it has no subscription to decide with, and the sanctioned path is its commit channel. Passthrough is decided by the repository, not by the location inside it. Where the repository's own root carries no declaration at all, the wrapper enforces nothing and execs the real git binary unmodified — the same transparent passthrough it applies outside tmux. Where the repository's root is itself a declared non-project invocation context, the seal covers the whole repository: an invocation beneath it that resolves to no context root is refused rather than passed through. A project repository is unchanged: its seal follows its subscriptions exactly as above, and every location beneath it resolves to the project's own context root.

The contract resolves four classes of file state at commit time:

1. **Modified-tracked** files in scope ride the pathspec straight from the working tree — the commit records the working-tree version, no staging needed.
2. **NEW (untracked)** files in scope are **dropped** from the pathspec unless declared via `telec code add <path>` or `--include <path>`. This is the safety net against incidental temp/scratch artifacts the agent's tool calls may have created.
3. **Partial-staged tracked** files (staged hunks + later working-tree delta) in the pathspec are **blocked** by the partial-staging guard. The diagnostic directs the agent at `telec code add <path>` as the recovery: it fully restages the file so the staged version matches the working tree, removing the ambiguity, after which the commit proceeds cleanly.
4. **Unmerged-index** files (post-conflict, pre-resolution-stage) in the pathspec are staged internally so the integrator's conflict-resolution flow runs through the same sealed path.

On a shared branch the scope itself is strictly `(live session declarations) ∩ (currently dirty paths) ∩ (the invocation context root's own material) ∩ (the repository's retained set, where its owner publishes one)`. In a linked worktree the declaration term does not apply and the scope is drawn from the worktree's dirty paths within the acting context root. Two acts declare a path: a successful `telec code add <path>...` writes each accepted path, with the instant it was declared, to the declaring session's own declaration record, and a successful edit-tool call whose input names the file it writes is declared the same way when the runtime reports that call (`sdlc/design/workspace-scoping`). The entry stays live until the commit that carries it lands. A path named only by shell-command text contributes no evidence, and no transcript is read to establish a declaration.

A context root's **own material** is what lies under it minus what belongs to another owner. Ownership is the test, not whether TeleClaude resolves a nested root as a context: a nested root belongs to another owner when it declares a different tier, when it anchors a context of its own, or when it holds a repository of its own, and any one of those is enough. So a person's material and a company's material are both foreign to the global context that encloses them, a person-owned project is foreign to the person context that encloses it, and an unrelated checkout nested anywhere is foreign to every context above it — including the cases that anchor no context at all.

The two halves answer different failures and neither substitutes for the other. Containment under the acting root separates sessions working under _different_ context roots of one repository, so a path outside the acting root is absent from the scope whatever the transcript claims. Subtraction of foreign-owned roots excludes what sits _inside_ the acting root, which containment alone cannot reach.

The retained set is the fourth term and its membership is not this contract's to compute: where a repository's owner publishes a membership answer, that owner answers for any path with exactly one of `retained`, `not-retained`, or `outside`, and attaches no instruction to it. What the answer means here is this contract's decision: only `retained` is eligible. `not-retained` and `outside` are alike ineligible however the path is reached — the first because the owner excludes it, the second because the owner has no standing over it — and neither is ever read as permission. A repository whose owner publishes no such answer carries no such term: there is nothing to consume, this surface neither invents nor substitutes one, and the first three terms carry the bound alone. Publication and its absence are both the owner's facts, read from the owner's contract.

Containment bounds every path that reaches inspection, staging, or commit — not only the computed scope. A path named through an explicit declaration or subset channel is subject to the same bound: naming a path does not admit material outside the acting context root's own material, and such a path is refused rather than carried.

Within a single context root, and outside any nested root, the scope remains transcript-derived and a path is still touched by being read, so two sessions working the same path there are not separated by this contract; that case belongs to dirty-path ownership attribution, not to scoping.

On the repo-root `main` branch, a non-integrator agent invoking `telec code commit` without `--approved` surfaces the **commit-first and review-routing gate** and does not commit. A bare invocation (no message) is discovery and **exits 0** — serving the gate is the successful outcome; an invocation that carries a message but omits `--approved` means the gate was forgotten and **exits non-zero**. `--approved` is the agent-owned sealed-gate acknowledgment that lets the commit proceed; it is not human approval. On a worktree or integrator role, `--approved` is still required but the gate surfacing is bypassed.

## Canonical fields

### Todo association

The optional `--todo <slug>` commit argument supplies the association described
by `general/policy/commits`. The sealed surface resolves existence from the
owning project's authoritative todo state and appends the inferred footer. A
slug that has not been created is valid association input and creates no todo,
reservation, claim, or dispatch. Lookup failure is reported as failure to resolve
the association, rather than interpreted as proof that the todo is absent
(`sdlc/principle/design-fundamentals`).

The two inferred footer names are normalized to one association when commit
provenance is read. The footer records commit-time evidence; it does not track
the todo's later lifecycle or authorize work. Existing identity, human
involvement, declared-file scoping and commit-review behavior keep their own
contracts.

### Use cases

#### UC-NCR-13 — Wrapper passes through transparently in an undeclared repository

```
Given an agent session running inside its host pane (identity present)
And the working directory is a git repo whose own root carries no declaration
When the agent invokes `git add`, `git commit`, `git rebase`, or `git push` in any form
Then the wrapper execs the real git binary unmodified
And no seal or role-guard error is printed
And the command's exit status and output are git's own
```

#### UC-GWR-1 — The integrator rows follow the role the caller's session record resolves to

```
Given an agent session in its host pane on `main` of a sealed repository
When it pushes to `origin main`, or runs a merge, rebase or cherry-pick that produces a commit on main
Then the wrapper admits it only when the session's record resolves to the integrator system role
And any other role is refused with the integrator-only message
```

#### UC-LMR-1 — A slug worktree cannot reference local main

#### UC-CGIP-41 — Bare telec code commit on main surfaces the commit-first review-routing gate

```
Given an agent on the `main` branch with a non-integrator role
When the agent invokes `telec code commit` with no message and no flags
Then the command prints the commit-first review-routing gate to stderr
And exits 0 — serving the gate is the successful outcome, not a failure
And the gate names review candidates by what the diff touches: functional code/tests → slow code review; doc snippets (docs/**) or authored agent artifacts → med doc-hygiene review; incorporated third-party skill packages under agents/global/skills/<name>/** → no review; neither → no review
And the gate states that the author decides whether each candidate owes review by what the commit set out to do
And the gate directs a commit through which the author wrote new or changed code or documentation content to an independent reviewer
And the gate directs a commit through which the author wrote neither — a removal, a merge of already-reviewed work, a validation or other mechanical repair — to the author's discard, `telec code stamp <sha> --verdict approve --reason <text>`
And the gate points at `telec code add` for declaring the authoritative commit scope
And the gate surfaces `--only` for splitting a declared set into separable intents
```

#### UC-CGIP-35 — telec code add declares a modified tracked file without staging it

```gherkin
Given a tracked file has only an unstaged working-tree edit that the session's native file records do not carry
When the agent declares that file through the sealed add surface
Then the command succeeds without changing the file's index state
And the declaration enters that session's scope
And the command reports the file as declared
```

#### UC-CGIP-33 — A declaration is one session's path evidence across every scope consumer

```gherkin
Given an agent session on a shared branch has a dirty repository file that its native file records do not carry
When the agent declares the path through the sealed add surface
Then change inspection, lint, sealed commit, and agent-stop checkpoint receive the path in that session's effective scope
And dirty-path ownership attributes the path to that session at the declaration time
And another session does not acquire the declaration
And the declaration remains effective after that session restarts or is handed off
And a sealed commit that lands while carrying the path ends the declaration
And a sealed commit that lands carrying an explicit subset ends only the declarations in that subset
And a declaration the landed commit did not carry stays live
And an invocation that produces no commit ends no declaration
And a declaration outlives every restart, handoff and revival of its session, and ends when that session closes
```

#### UC-CGIP-34 — Sealed add serializes its index mutation with sealed commit

```gherkin
Given one session is inside the sealed commit's main-branch critical section
And another session invokes the sealed add surface for a path that requires staging
When the add operation reaches the shared Git index
Then it waits on the same main-branch serialization and index-lock recovery path as sealed commit
And it either stages the declared path after the index becomes available or fails with the existing bounded lock diagnostic
And it does not fail merely because the concurrent commit temporarily owns the index lock
```

#### UC-CGIP-44 — A declaration does not depend on the shape of the command that carried it

```gherkin
Given an agent session on a shared branch invokes the sealed add surface for a dirty path
And the invocation is carried by a pipeline, a redirection, a chained command, a heredoc, or a script
When the command succeeds
Then exactly the named paths are live declarations for that session
And no shell operator, redirection target, or neighbouring command name is a declaration
And the session's effective scope is the same as for a bare invocation of the same paths
```

### Use cases

- **Routine agent edit-and-commit:** modify tracked files; run `telec code commit --approved "<msg>"`; pathspec ride takes them via working tree; no `git add` ever invoked by the agent.
- **Agent introduces a new file:** `telec code add <new>` before commit (incremental) OR `--include <new>` at commit time (one-shot). Either declares intent so the safety net releases the file.
- **Agent recovers from accidental partial-staging:** `telec code add <file>` fully restages; commit retries cleanly.
- **Integrator conflict resolution after a squash merge:** edit resolved file; `telec code add <resolved>`; `telec code commit --approved "<msg>"`.
- **Bash-`rm` deletion that fell out of transcript:** `telec code commit --approved "<msg>" --include <deleted>` declares the deletion explicitly.

### Commit-time gates — the pre-commit hook, no framework stash

The installed `.git/hooks/pre-commit` (`telec code pre-commit`) runs, for every
route into a commit, the checks each staged path's owning home carries, never
selected by the directory the commit started from. Whether the gate runs, and
which checks it runs, follow the capability rule in
`local/projects/teleclaude/spec/feature/config/project-capability-manifest`: the gate
runs where the owning home carries `code` or `docs`, a global, person, or
company home counting as `docs` and `agents` by its kind
(`local/projects/teleclaude/spec/feature/config/tier-permissions`), and each capability
contributes only its own checks. A home carrying neither is not gated, no check
is applied in its place, and the commit proceeds directly. The checks run
against the commit's staged file set, after the partial-staging guard.
Formatting is checked and never rewritten. The documentation and agent-artifact
validators read the staged content against the rest of each owning home as
committed, never against another session's uncommitted files; the native leg
runs on disk over the staged files, which the partial-staging guard makes
identical to what is staged. `telec code commit` formats `quality_paths` (the
commit pathspec filtered to existing files) and then runs `git commit` without
`--no-verify`, so it passes the same hook as a raw `git commit`. No framework
stash occurs; files outside the pathspec are not touched.

The commit message follows `general/policy/commits`, and a commit is created
only when the message and every applicable staged-file gate pass. A refusal
leaves no commit. If the change contains only deletions, no existing file is
formatted or checked by the native leg, but documentation and agent-artifact
validation still assess each affected home as it will stand after deletion.

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

```
Given a non-integrator agent on main invokes telec code commit without --approved
When the commit-first gate is surfaced
Then the card carries a per-file diffstat of the resolved commit scope against HEAD
And a resolved scope holding no change says so instead of printing an empty stat
And a scope that cannot be resolved says so and directs the agent to read the diff itself
```

#### UC-CGIP-10 — Merge commit degrades to a full-index commit with no pathspec in a single-owner tree

```
Given MERGE_HEAD is present (an active merge, resolved via repo.git_dir so it holds inside worktrees)
And the repository's own root is not a declared non-project invocation context
And every conflicted path has been resolved and staged (no remaining unmerged-index entries)
When agent invokes telec code commit --approved "<msg>"
Then quality_paths is the full merge diff (merge-base..MERGE_HEAD), not the caller's pathspec
And format runs over quality_paths, and the pre-commit hook grades the full staged merge result; a tier carrying no gate runs none
And repo.git.commit is called without "--no-verify" and with no trailing "--" pathspec
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

#### UC-CGIP-12a — Slug worktree refuses agent-artifact source paths

```
Given a slug worktree at trees/<slug> (a worktree that is not trees/_integration)
And the resolved commit pathspec contains one or more paths under agents/**
When agent invokes telec code commit --approved "<msg>"
Then SystemExit(1) names each offending agents/** path
And no commit occurs
And neither handle_format nor handle_lint is invoked
And the refusal reports the paths as agent-artifact sources rather than as doc-layer paths
And the refusal directs the agent to author the artifacts on main in the session where their intent was decided
```

#### UC-CGIP-13a — Main branch and integration worktree are unaffected by the agent-artifact refusal

```
Given the commit pathspec contains a path under agents/**
When the invocation is on the repo-root main branch, or in the integration worktree at trees/_integration
Then the agent-artifact refusal does not fire
And the commit proceeds subject to the other commit-time invariants
```

#### UC-CGIP-29 — The pre-merge worktree sync refuses agent-artifact source paths

```
Given a slug worktree at trees/<slug> whose working tree carries uncommitted changes
And one or more of those dirty paths is under agents/**
When the work state machine syncs that worktree against origin/main before merging
Then no path is staged and no pre-merge sync commit is created
And the sync returns an error naming each offending agents/** path
And the error reports the paths as agent-artifact sources rather than as doc-layer paths
And the error directs the agent to author the artifacts on main in the session where their intent was decided
```

#### UC-CGIP-14 — An unresolvable transcript neither errors nor withdraws the session's declarations

```
Given a telec code invocation bound to an agent session on the repo-root shared branch
And that session has no resolvable transcript to scope its changes from
When the workspace scope is resolved
Then the session's native touched-path scope resolves as empty and the resolution returns normally
And the session's declared paths are still resolved from its declaration record
And no path the session neither touched nor declared is admitted to the commit pathspec
And the resolution never widens to the dirty worktree
```

#### UC-CGIP-15 — Sealed commit stamps the agent's author identity and appends the session trailer

```
Given an agent session with a resolvable active agent commits through telec code commit --approved
When the commit lands
Then the commit's git author is that agent's verified bot identity
And the commit's git committer remains the human account identity the work runs under
And the message has a Session: <session id> trailer appended after the branding line
```

#### UC-CGIP-17 — A person the platform resolves at a terminal degrades honestly to the human as author

```
Given a telec code commit invocation from outside any agent session
And the platform resolves the invoking caller as a registered person from their terminal login
When the commit lands
Then git's own ambient identity resolves the author
And the message carries no Session: trailer
```

#### UC-CGIP-18 — A caller the platform cannot identify fails the commit loudly

```
Given the platform resolves the invoking caller as neither an agent session nor a registered person
When telec code commit is invoked
Then the commit fails loudly with a diagnostic
And no commit is produced attributing the change to whichever identity git's ambient config happens to name
```

#### UC-CGIP-47 — Commit attribution resolves from the carried identity

```
Given an agent session whose record names its active agent
And the platform's local service is not reachable from the invoking process
When telec code commit --approved is invoked from that session
Then the commit's git author is that agent's verified bot identity, resolved from the session record
And no request is sent to the platform's local service to resolve the author
And a principal copied into the session identity document never decides the author
```

#### UC-CGIP-16 — Human-Involved is a per-commit declaration, never derived from the todo record

```
Given the commit is made inside a todo's own slug worktree
And that todo's recorded human_involved fact is true
And telec code commit is invoked without --human-involved
When the commit lands
Then the message has Human-Involved: false appended
And the commit path reads no todo record to decide the value
```

#### UC-CGIP-19 — Human-Involved defaults to false when no declaration is made

```
Given telec code commit is invoked without --human-involved
When the commit lands
Then the message has Human-Involved: false appended
```

#### UC-CGIP-20 — Human-Involved is true when the committing session's observed human input is recent

```gherkin
Given the committing agent invokes telec code commit with a non-empty human-involvement reason
And the session's latest authenticated human input falls within the code-owned recency window
When the commit lands
Then the message has Human-Involved: true appended
And the record is resolved in the committing process from the session store it reads directly
And no request is issued to the daemon to resolve the record
And the reason remains only in the invoking session's transcript
And the reason is absent from the commit message, command output, logs, events, and every other durable record
And the declaration changes no authorization, scope, gate, or later action
```

#### UC-CGIP-38 — Human involvement requires a non-empty invocation reason

```gherkin
Given an agent invokes telec code commit with a missing or blank human-involvement reason
When the sealed surface validates the invocation
Then it refuses the declaration before producing a commit
And it emits no supplied reason
And the diagnostic directs the agent to rerun without the declaration when the act is not human-involved
```

#### UC-CGIP-39 — Stale human activity records false and the commit lands

```gherkin
Given an agent invokes telec code commit with a non-empty human-involvement reason
And the session's latest authenticated human input is absent or older than the code-owned recency window
When the sealed surface resolves the record
Then the message has Human-Involved: false appended
And the commit lands exactly as it would have without the declaration
And no authorization or commit-content decision changes
```

#### UC-CGIP-42 — A discarded commit declaration is observable with its age

```gherkin
Given an agent invokes telec code commit with a non-empty human-involvement reason
And the session's latest authenticated human input is absent or older than the code-owned recency window
When the sealed surface resolves the record to false
Then a structured record reports the discard, the acting session's full identifier, and the observed age of the last human input
And that record carries no part of the supplied reason
```

#### UC-CGIP-43 — An unreachable session store records false rather than failing the commit

```gherkin
Given an agent invokes telec code commit with a non-empty human-involvement reason
And the session store cannot be read
When the sealed surface resolves the record
Then the message has Human-Involved: false appended
And the commit lands
```

#### UC-CGIP-40 — Human involvement never propagates between commits

```gherkin
Given one commit recorded Human-Involved: true
When the same session later creates another commit without a human-involvement declaration
Then the later commit records Human-Involved: false
And no session, todo, branch, parent act, or earlier commit supplies the later value
```

#### UC-CGIP-21 — A pre-existing tool-shaped line in the message is left untouched, not enforced against

```
Given the message already contains a line such as Agent:, Co-Authored-By, or Signed-off-by:
When the commit lands
Then that line survives exactly as written
And the sealed surface still appends its own branding line, Session:, and Human-Involved: after it
And the commit is not rejected and the line is not stripped, merged, or otherwise edited
```

#### UC-CGIP-24 — The integrator's worktree-cleanup commit carries the full footer

```
Given the integrator commits a residual staged fold as part of delivering a todo
When the worktree-cleanup commit lands
Then the commit's git author is the integrator's verified bot identity
And the commit's git committer remains the human account identity the work runs under
And the message carries the branding line, a Session: line for the integrator's own session, and Human-Involved: false, since no agent declares involvement at this call site
And the message carries no Co-Authored-By line
```

#### UC-CGIP-25 — The pre-merge worktree sync commit carries the full footer

```
Given the builder's own worktree is synced against origin/main mid-build and the sync leaves changes to commit
When the pre-merge sync commit lands
Then the commit's git author is the builder's verified bot identity
And the commit's git committer remains the human account identity the work runs under
And the message carries the branding line and a Session: line for the builder's own session
And the message carries Human-Involved: false, since no agent declares involvement at this call site
And the message carries no Co-Authored-By line
```

#### UC-CGIP-32 — A declared path the repository cannot match is refused before git runs

```gherkin
Given an agent declares several paths on a sealed commit
And one declared path names nothing the repository can match, while the others carry real changes
When the sealed commit runs
Then the commit is refused before git is invoked
And the diagnostic names each unmatchable declared path
And the refusal is attributed to the declaration rather than reported as a raw git pathspec error
And no commit is created
```

#### UC-NCR-1 — Change inspection from a context root below the repository root

```
Given an agent session whose context root sits below the root of the repository that contains it
When the agent inspects the changes in scope
Then the reported paths are expressed relative to its own context root
And every reported path lies inside that context root's subtree
```

#### UC-NCR-2 — A commit from a nested context root lands only that context's changes

```
Given an agent session whose context root sits below the root of the repository that contains it
And the session has changes in scope
When the agent commits through the sealed surface
Then the commit contains exactly those changes
And the commit is recorded in the repository that contains the context root
```

#### UC-NCR-3 — Concurrent work elsewhere in the same history is untouched

```
Given one repository containing several context roots
And another session has uncommitted work under a different context root
When an agent commits from its own context root
Then the other session's work is neither included in the commit nor altered
```

#### UC-NCR-4 — A foreign nested root is not carried

```
Given a context root containing a nested root owned by someone else
And that nested root has uncommitted changes
When an agent commits from the enclosing context root
Then the nested root's changes are not carried by the commit
```

#### UC-NCR-5 — The eligible change set is inspectable before committing

```
Given an agent session whose context root sits below the root of the repository that contains it
When the agent asks what a commit would carry, naming any explicit path declarations it intends to make
Then it is shown exactly the eligible payload the so-declared commit would carry, in its own coordinates
And material owned by another context, a foreign nested root, or excluded from a retained set the repository's owner publishes is absent from that set
```

#### UC-NCR-6 — Containment outranks the session's own path set

```
Given an agent session whose transcript-derived path set names a dirty path outside its context root's own material
When the agent inspects its scope and commits
Then that path is absent from the reported scope
And the commit does not carry it
```

#### UC-NCR-7 — The seal holds at an invocation context root that is not a project

```
Given an invocation context root whose tier carries no project subscriptions
When an agent working there invokes raw `git commit` or `git add`
Then the wrapper refuses and points at the sealed surface
And the raw invocation produces neither a commit nor a staged change
```

#### UC-NCR-8 — An invocation context carrying neither subscriptions nor a participating surface commits with no gates and no substitute

```
Given an agent working in an invocation context root whose tier carries no project subscriptions
And whose tier's material participates in no surface
And that context root has changes in scope
When the agent commits through the sealed surface
Then no subscription-gated check runs, and no check is applied in place of one
And the commit is produced
```

#### UC-NCR-14 — A home declaring no capabilities gets only the documentation checks

```
Given an agent working in a person home, which declares no capability blocks
And that home has changes in scope
When the agent commits through the sealed surface
Then the gate runs over the staged files
And snippet validation runs over them, and artifact validation over any agent artifacts among them, because the home counts as docs and agents by its kind
And neither the native toolchain nor TeleClaude's code rules run, because the home does not carry code
And no native toolchain contract is required at that root for the commit to proceed
```

#### UC-NCR-15 — A tier carrying code still requires its native toolchain

```
Given an agent working in an invocation context root whose tier carries code
And that root has no native toolchain contract
And that root has changes in scope
When the agent commits through the sealed surface
Then the gate fails loudly rather than skipping the native toolchain leg
And no commit is produced
```

#### UC-NCR-9 — A context root that is also the repository root is unchanged

```
Given an agent session whose invocation context root is itself the root of the repository containing it
And that checkout holds no foreign-owned nested root and its repository publishes no retained set
When the agent inspects its changes and commits through the sealed surface
Then the reported paths and the commit's contents are what they were before the context root became a separate coordinate
And the gates that run are the ones that ran before
```

#### UC-NCR-10 — A declared path outside the acting context's own material is refused

```
Given an agent working in an invocation context root
And a dirty path that lies outside that context root's own material
When the agent names that path through any explicit declaration or subset channel
Then the command refuses, naming the path
And no commit or staged change carries it
```

#### UC-NCR-12 — A commit taken mid-merge does not escape the bound

```
Given a repository whose own root is a declared non-project invocation context
And a merge is in progress in that repository
When an agent commits through the sealed surface
Then the commit carries no material outside the acting context's eligible set, or the commit is refused
And no commit state falls back to recording the whole index
```

#### UC-NCR-11 — A location with no context root inside a sealed repository cannot reach raw git

```
Given a repository whose own root is a declared non-project invocation context
And a location beneath it at which invocation resolves to no context root
When an agent working there invokes raw `git commit` or `git add`
Then the wrapper refuses rather than passing through to the real git binary
And the repository's history is not mutated by that invocation
```

### Pre-commit hook gate

#### UC-TH-1 — Thin hook partial-staging backstop

```
Given agent bypasses telec and invokes raw git commit with partially staged files
When the thin .git/hooks/pre-commit runs
Then it detects the overlap via NUL-safe Python (no unquoted shell expansion)
And exits non-zero naming the partially staged paths
And no INSTALL_PYTHON is present in .git/hooks/pre-commit
```

#### UC-TH-2 — The hook passes clean commits

```
Given working tree has no partially staged files
And the staged file set passes every gate the acting tier carries
When raw git commit is attempted
Then .git/hooks/pre-commit exits 0
And the commit proceeds
```

#### UC-TH-3 — Thin hook fails closed on git status probe failure

```
Given the git status probe (git status --porcelain=v1 -uall -z) returns nonzero
When the thin .git/hooks/pre-commit runs
Then the hook exits nonzero immediately
And the commit is aborted
And the partial-staging check is NOT silently bypassed
```

#### UC-TH-4 — A raw git commit and telec code commit get the same verdict

```gherkin
Given two identical file sets in the same context root
When one is committed with raw git commit from a terminal
And the other with telec code commit --approved
Then the pre-commit hook runs the same checks over both staged file sets
And both commits land, or both are refused with the same findings
```

#### UC-TH-5 — Another session's uncommitted file does not decide a commit

```gherkin
Given a nested home in which one session holds an uncommitted invalid snippet
And another session stages a valid snippet change in the same home
When the second session commits
Then the hook grades the staged snippet against the home as committed
And the commit lands
And the first session's uncommitted file stays dirty and unjudged
```

#### UC-TH-6 — A context without code is still gated for its documentation

```gherkin
Given a person or company home whose tier carries no code capability
When an invalid snippet in that home is committed by any route
Then the pre-commit hook refuses the commit, naming the finding
And no commit is created
```

#### UC-TH-7 — The hook checks formatting and never rewrites a file

```gherkin
Given a staged file that its formatter would change
When raw git commit is attempted
Then the hook refuses the commit and names the format command for that file
And the file on disk and in the index is unchanged
```

#### UC-TH-8 — A merge commit git creates on its own passes the same gate

```gherkin
Given a merge that git completes without conflicts and records as a merge commit
When the merge runs, from a terminal or from an automated route
Then the same gate grades the staged merge result before the merge commit is recorded
And a refusal leaves no merge commit
```

#### UC-CGIP-49 — A file written through an edit tool is committed without an explicit declaration

```gherkin
Given an agent session on a shared branch edits a file through an edit tool whose input names that file
And the tool call succeeds
When the session runs `telec code commit --approved '<message>'` without declaring the file
Then the file is committed as part of the session's declared set
But a file the session changed only through a shell command is not committed until the session declares it
```

### Branch publication

A successful sealed commit in a todo worktree whose checked-out branch is that todo's branch publishes it to the project's `origin` remote, so every task commit exists off the computer that made it. Publication follows the commit and never decides it: the commit is recorded before any push is attempted, and no publication outcome changes the commit or the command's success.

If publication fails, the local commit remains and the command still reports
success while telling the agent publication failed with its cause; the next
commit retries publication. A rewritten branch replaces the remote branch only
when the remote has no unseen work; otherwise publication is refused and that
remote work remains intact. A commit on main or in the integration worktree
does not publish. Without an origin remote, nothing is pushed and no publication
message is added. From a worktree on another branch, nothing is pushed and the
agent is told why.

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

## See also

- docs/local/design/code-commit.md
- docs/global/sdlc/policy/version-control-safety.md
