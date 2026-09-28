---
description: Commitizen format, attribution, when to commit. Atomic commits, hooks
  verify quality.
visibility: public
---

# Commits — Policy

## Rules

This is the canonical source of commit behavior. Other docs may reference it, but must not redefine commit policy.

Use commitizen format:

```
type(scope): subject

🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)

Session: <teleclaude session id>
Human-Involved: <true|false>
```

- The agent that produced the change is its author, stamped mechanically in the
  git author field by the sealed commit surface — no message trailer carries it.
- The human is never an author. Their name and email never appear in the message
  body. The human's git identity remains on the commit only as the committer —
  the account the work runs under, lineage, never authorship.
- The sealed commit surface appends the branding line, `Session:`, and
  `Human-Involved:` to whatever message it receives — it never reads, parses,
  or edits that message to enforce this or anything else. `Session:` is
  present whenever an agent session resolves — the revival handle
  (`telec sessions revive <id>`) for that exact commit.
- `Human-Involved:` is a bare `true`/`false` with no identity attached and is
  always present. It records only whether a human shaped this commit; omission
  records `false`. The declaration is made through the sealed commit surface,
  whose point-of-use contract owns its admissibility. It is never derived from
  a todo, session launch, lineage, preceding act, or message text, and it
  supplies no declaration for any later commit.
- `Co-Authored-By`, `Agent:`, and `Signed-off-by` trailers are prohibited —
  the git author field is what carries attribution. The sealed surface does
  not enforce this by inspecting messages: a message that contains one
  survives untouched, appended to rather than corrected.

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
<!-- planned-change:declared-ownership-capture -->
- **Stranded paths on main are committed by the integrator.** A dirty path that
  blocks repo-root synchronization is put to every live session that can have
  written it, and a session whose change is not released for commit claims the
  path instead of committing it. A path no session claims, and that stays unwritten
  past the next clearance beat, has no owner left to release it; the integrator
  commits it as-is under `sdlc/procedure/lifecycle/integrate`. This is the only
  commit made of another session's uncommitted work.
<!-- change:declared-ownership-capture -->
- **Stranded paths on main are committed by the integrator.** A dirty path that
  blocks repo-root synchronization goes to the session that declared it, or, when
  none did, to the live sessions whose history shows they wrote it; a session whose
  change is not released for commit claims the path instead of committing it. A
  path no session claims, and that stays unwritten past the next clearance beat,
  has no owner left to release it; the integrator commits it as-is under
  `sdlc/procedure/lifecycle/integrate`. This is the only commit made of another
  session's uncommitted work.
<!-- /planned-change:declared-ownership-capture -->
- Before committing on shared `main`, run bare `telec code commit` to surface
  the gate card, then commit with `telec code commit --approved "<message>"`,
  which commits the set the session declared. Pass `--only <path>...` to split
  that set across more than one commit.
<!-- planned-change:declared-ownership-capture -->
- Declare every file you change with `telec code add <path>...`. Do it as you
  start on a file, or the moment you notice one isn't declared — late is fine,
  never is not. The declared set is what `telec code commit` commits, so an
  undeclared change does not ship. Declaring is free and repeats safely; when in
  doubt, declare.
<!-- change:declared-ownership-capture -->
- A file you write with an edit tool is declared for you when the call succeeds.
  Declare every file you change any other way — a shell command, a script, a
  generator — with `telec code add <path>...`, as you start on it or the moment
  you notice it isn't declared; late is fine, never is not. The agent-stop
  checkpoint names dirty files your shell commands wrote that you have not
  declared. The declared set is what `telec code commit` commits, so an
  undeclared change does not ship. Declaring is free and repeats safely; when in
  doubt, declare.
<!-- /planned-change:declared-ownership-capture -->
- Post-commit review is routed by the committed diff, not by pre-commit
  permission. Functional code/tests are committed first. When the post-commit
  gate determines that independent review is required, the authoring session
  dispatches it automatically and waits for the verdict; review is technical
  stewardship, never a human ratification step. A `REQUEST CHANGES` verdict
  stays with the authoring session for evidence-based rejection or in-scope
  remediation and re-review. Only a genuine human-owned decision, an unresolved
  contract deadlock, or a safety gate is carried to the human.
  Governed contracts (documentation snippets) and agent artifacts require
  independent review after commit. The main-branch checkpoint's code-scoped
  review gate applies to every committed non-documentation path; runtime path
  classification does not infer a weaker review obligation from whether a file
  appears to be bookkeeping.

## Rationale

Attribution names the party that did the work. The human's git identity is on
every commit because it is the account the work runs under — lineage, not
authorship — and their credential already occupies the committer field, so
repeating their name in the body asserts the same thing twice and reads as
authorship. Standing trailers assert involvement that did not happen.

The surface's own footer and its unset author field are properties of the tool,
not choices a committing agent makes: an agent has no channel to suppress the one
or set the other. Attributing either to the commit's author would file a tool
limitation as that author's mistake — the inversion this policy exists to prevent.

- Consistent commits enable reliable rollbacks and audits.
- Commit messages drive automated release notes and changelogs.
- Asking before routine commits shifts technical stewardship back to the human
  and leaves completed work unrecorded. The safety boundary is the sealed commit
  gate plus post-commit review routing, not a human permission prompt.

A shell command's text does not reveal which files it wrote. Reading paths out
of that text mistakes files the command merely inspected or quoted as prose for
files it changed. The session that ran the command declares what it wrote; the
runtime's file-edit records cover edits made through native tools.

## Scope

- Applies to all repositories and all contributors.

## Enforcement

`telec code commit` is the canonical commit interface. The wrapper handles workspace scoping, staging, and pre-commit hooks automatically; direct git operations are blocked and self-document at the error path.

The tool-appended `Co-Authored-By` line and the ambient git author on a commit are
never findings against that commit or the agent that made it. Every commit made
through the surface carries both.

Commit guidance, CLI help, agent addenda, and project-specific designs must not
describe `--approved` as human approval or require a pre-commit human decision
for autonomously authorized work. They may reference this policy and document
mechanics, but the commit-first rule and the human-conversation boundary live
here.

## Exceptions

- Emergency production fixes may allow minimal commits with a follow-up cleanup task.
