---
description: Commitizen format, attribution, when to commit. Atomic commits, hooks
  verify quality.
visibility: public
---

# Commits — Policy

## Rules

This is the canonical source of commit behavior. Other docs may reference it, but must not redefine commit policy.

Write a Commitizen subject and, when useful, an explanation of the change:

```
type(scope): subject
```

- Author only the subject and explanatory body. The sealed commit interface
  owns attribution and provenance. The message describes the work, not who
  performed or authorized it (`general/concept/lineage-vs-authorship`).
- Declare human involvement through the command's action-scoped option under
  `general/policy/human-involvement-recording`.

**Todo association:**

For documentation prepared for a future todo, choose the fitting slug before
committing and supply it through `telec code commit --todo <slug>`. Choosing the
slug creates and reserves no todo. Work associated with an existing todo uses
the same flag. Work outside a todo keeps its ordinary commit path.

**Valid types:**

All Committizen types are allowed.

**Scope:** Component or area affected (optional but recommended)

**Subject:** Clear, concise description in imperative mood

- One logical change per commit
- Keep commits small and focused
- Commit message explains WHY, not WHAT (code shows what)
- Update or add tests when behavior changes.
- Include migration notes when schema or data shape changes.
- Squash noisy fixups before merge to keep history readable.
- **`[skip ci]` for automation bookkeeping.** Any commit pushed to origin/main that contains only scaffolding, roadmap updates, or other non-code bookkeeping MUST include `[skip ci]` in the commit subject line. CI runs are reserved for actual code delivery. The integration push from `trees/_integration/` is the only push that should trigger CI.
- **Commit authorized, coherent work first; then route review.** Committing is
  part of normal autonomous agent work once the current authoring context has
  produced a stable change it is authorized to materialize. A dispatched worker
  or an agent-owned autonomous session does not ask the human for routine commit
  permission. In
  `telec code commit --approved`, `--approved` means the agent has passed the
  commit gate and owns the pathspec-scoped commit; it does not mean the human
  approved the commit.
- **Automation reports commit state; it never creates commit authority.** A
  checkpoint, stop hook, dirty-tree card, or tool result may require attention
  under its governing contract, but it does not turn a forming human
  conversation into a finished change. Where the human has not released the
  tracked change for commit, report what remains uncommitted and offer to
  commit; do not commit it, revert it, or suppress the automation.
- **Stranded paths on main are committed by the integrator.** A dirty path that
  blocks repo-root synchronization goes to the session that declared it, or, when
  none did, to the live sessions whose history shows they wrote it; a session whose
  change is not released for commit claims the path instead of committing it. A
  path no session claims, and that stays unwritten past the next clearance beat,
  has no owner left to release it; the integrator commits it as-is under
  `sdlc/procedure/lifecycle/integrate`. This is the only commit made of another
  session's uncommitted work.
- Before committing on shared `main`, run bare `telec code commit` to surface
  the gate card, then commit with `telec code commit --approved "<message>"`,
  which commits the set the session declared. Pass `--only <path>...` to split
  that set across more than one commit.
- A file you write with an edit tool is declared for you when the call succeeds.
  Declare every file you change any other way — a shell command, a script, a
  generator — with `telec code add <path>...`, as you start on it or the moment
  you notice it isn't declared; late is fine, never is not. The agent-stop
  checkpoint names dirty files your shell commands wrote that you have not
  declared. The declared set is what `telec code commit` commits, so an
  undeclared change does not ship. Declaring is free and repeats safely; when in
  doubt, declare.

- Post-commit review is routed by the committed diff, not by pre-commit
  permission. Functional code/tests are committed first. The post-commit gate
  names the commits that are review candidates; the authoring session decides
  for each whether independent review is owed, by what a wrong change would
  cost. Review is owed when the change carries a consequence its author cannot
  establish alone: new or changed logic, a state or data shape, a contract
  between components, concurrency, security, or what a governed snippet or
  agent artifact directs other agents to do. The author dispatches that
  reviewer and waits for the verdict. Every other commit is stamped `approve`
  by its author with `telec code stamp` and a one-line reason, without asking
  anyone: a removal, a merge of work already reviewed where it was written, a
  validation or mechanical repair, a rename or move, formatting, and wording or
  prompt prose whose effect is presentation. Content its owner judged while it
  was being written — wording a human shaped with the authoring session — is
  already reviewed where it was written. Which paths the diff touches names the
  candidate; it never decides that review is owed. Stamping is not reviewing;
  it records that no review is owed, never that the change is correct. Review
  is technical stewardship, never a human ratification step.

- Every commit-review outcome is a repository-owned record keyed by the commit
  SHA, available independently of whether a todo exists or a session holds its
  claim. The record carries the verified stamping session, verdict, time and
  reason. The reviewer stamps exactly the commits reviewed; an author's discard
  remains distinguishable and supplies no independent review approval. Todo
  review state consumes this same record rather than owning a separate verdict.
  A stamp with no claimed todo still persists and discharges its applicable
  checkpoint obligation. This keeps pre-creation documentation approval
  available as evidence without reconstructing a transcript
  (`general/principle/grounding`).
- An approval is independent only when its authenticated stamping session is
  distinct from every producing session recorded by the reviewed commit's
  platform-recorded provenance. An approval from a producing session, or one
  whose reviewer or producing-session provenance cannot be established, supplies
  no independent approval evidence. The creation boundary consumes that
  established provenance with the SHA-bound verdict; it never accepts a caller's
  assertion of independence. Author discard stamps retain their existing
  purpose and do not become review approvals
  (`general/concept/lineage-vs-authorship`).

<!-- planned-change:issue-128 -->

- A `REQUEST CHANGES` verdict stays with the authoring session for
  evidence-based rejection or in-scope remediation and re-review. Before
  remediation, the author records each finding's disposition and its
  independently established basis in the follow-up to the continuing reviewer,
  applying the finding-validation and disposition rules in
  `sdlc/procedure/lifecycle/fix-review-findings`. After remediation, the
  follow-up identifies the fixing commits and closure evidence; an
  evidence-only rejection names its sources. For commit review, this exchange
  carries the disposition record, and the stamp records only the verdict. The
  author retains commit and review-routing responsibilities; the reviewer alone
  determines the verdict. What cannot proceed — a genuine human-owned decision,
  a safety gate, or a disagreement author and reviewer cannot resolve — is
  held, and the session goes idle with it; nothing routes it to another party
  (`general/principle/autonomy`).
  The main-branch checkpoint's code-scoped review gate applies to every
  committed non-documentation path; runtime path classification does not infer
  a weaker review obligation from whether a file appears to be bookkeeping.
  The authoring session owns acting on its review verdict — remediation,
  re-review routing and recovery; the verdict itself is the reviewer's. The standing
  integrator publishes committed canonical main after its own maintenance and
  any owed log judgment; it does not inspect or wait for other sessions' review
  verdicts, and their review state is not a direct-main publication gate.

<!-- change:issue-128 -->

- A `REQUEST CHANGES` verdict stays with the authoring session for
  evidence-based rejection or in-scope remediation and re-review. Before
  remediation, the author records each finding's disposition and its
  independently established basis in the follow-up to the continuing reviewer,
  judging each finding's validity by the rule of
  `sdlc/procedure/lifecycle/review`. After remediation, the
  follow-up identifies the fixing commits and closure evidence; an
  evidence-only rejection names its sources. For commit review, this exchange
  carries the disposition record, and the stamp records only the verdict. The
  author retains commit and review-routing responsibilities; the reviewer alone
  determines the verdict. What cannot proceed — a genuine human-owned decision,
  a safety gate, or a disagreement author and reviewer cannot resolve — is
  held, and the session goes idle with it; nothing routes it to another party
  (`general/principle/autonomy`).
  The main-branch checkpoint's code-scoped review gate applies to every
  committed non-documentation path; runtime path classification does not infer
  a weaker review obligation from whether a file appears to be bookkeeping.
  The authoring session owns acting on its review verdict — remediation,
  re-review routing and recovery; the verdict itself is the reviewer's. The standing
  integrator publishes committed canonical main after its own maintenance and
  any owed log judgment; it does not inspect or wait for other sessions' review
  verdicts, and their review state is not a direct-main publication gate.

<!-- /planned-change:issue-128 -->

## Rationale

The committing agent owns the explanation of the change; the platform owns its
verified attribution and provenance. Operating guidance supplies the command
arguments that carry the author's intent, rather than metadata representations
that invite the author to imitate platform output (`general/principle/priming`).

- Consistent commits enable reliable rollbacks and audits.
- Commit messages drive automated release notes and changelogs.
- Asking before routine commits shifts technical stewardship back to the human
  and leaves completed work unrecorded. The safety boundary is the sealed commit
  gate plus post-commit review routing, not a human permission prompt.
- A review is worth what it can catch. It earns its cost where a wrong change
  does damage its author cannot see and an outside standard can find it. A
  change whose error shows at a glance and undoes in a moment, or whose only
  standard is the judgment its owner already applied, gives the reviewer
  nothing to check: the review spends a session and the human's attention and
  verifies nothing. Deciding by what the commit touches instead of what it
  risks turns every edit to a code file into a review cycle.

A shell command's text does not reveal which files it wrote. Reading paths out
of that text mistakes files the command merely inspected or quoted as prose for
files it changed. The session that ran the command declares what it wrote; the
runtime's file-edit records cover edits made through native tools.

## Scope

- Applies to all repositories and all contributors.

## Enforcement

`telec code commit` is the canonical commit interface. The wrapper handles workspace scoping, staging, and pre-commit hooks automatically; direct git operations are blocked and self-document at the error path.

The sealed interface refuses caller-supplied platform metadata before committing.
Its refusal directs the caller to submit a subject and explanation through the
supported command arguments. Reviewers judge authored content and command use;
generated provenance defects belong to the platform implementation.

Commit guidance, CLI help, agent addenda, and project-specific designs must not
describe `--approved` as human approval or require a pre-commit human decision
for autonomously authorized work. They may reference this policy and document
mechanics, but the commit-first rule and the human-conversation boundary live
here.

## Exceptions

- Emergency production fixes may allow minimal commits with a follow-up cleanup task.
