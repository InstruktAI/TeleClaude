---
description: 'Commitizen format, attribution, when to commit. Atomic commits, hooks verify quality.'
visibility: 'public'
---

# Commits — Policy

## Rules

This is the canonical source of commit behavior. Other docs may reference it, but must not redefine commit policy.

<!-- planned-change:commit-author-must-be-the-agent -->

Use commitizen format:

```
type(scope): subject
```

- The agent that produced the change is its author. The human is never an author;
  their name and email never appear in the message body.
- **Agents write no trailers of any kind.** The sealed commit surface owns the
  entire footer and appends it itself. An agent never adds an authorship line, a
  co-author line, a tool-attribution line, or an involvement line.
- The footer the surface appends is the tool branding line plus a
  `Co-Authored-By: TeleClaude` line. The surface sets no git author, so the author
  and committer fields both carry the ambient repository identity — the human
  account the work runs under.

<!-- change:commit-author-must-be-the-agent -->

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
- `Human-Involved:` is a bare `true`/`false` with no identity attached,
  always present. It is a declaration by the agent making the commit, from its
  own awareness of whether a human was present in that session — passed as the
  `--human-involved` flag to `telec code commit` and defaulting to `false` when
  no declaration is made. It is never derived from a todo's recorded
  `human_involved` fact, never inferred from where the commit is made, and
  never read from the message text.
- `Co-Authored-By`, `Agent:`, and `Signed-off-by` trailers are prohibited —
  the git author field is what carries attribution. The sealed surface does
  not enforce this by inspecting messages: a message that contains one
  survives untouched, appended to rather than corrected.

<!-- /planned-change:commit-author-must-be-the-agent -->

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
- **Commit first, then route review.** Committing is part of normal autonomous
  agent work. An agent that has completed a coherent change commits it through
  the sealed interface without asking the human for commit permission. In
  `telec code commit --approved`, `--approved` means the agent has passed the
  commit gate and owns the pathspec-scoped commit; it does not mean the human
  approved the commit.
- Before committing on shared `main`, run bare `telec code commit` to surface
  the gate card, then commit with `telec code commit --approved "<message>"`
  using the scoped pathspec the tool resolves. New untracked files require
  explicit inclusion through `telec code add <path>` or `--include <path>`.
- Post-commit review is routed by the committed diff, not by pre-commit
  permission. Functional code/tests are committed first; if independent review
  is warranted, the agent states the recommendation and dispatches review if
  the human stays silent for the policy-defined timer. Governed contracts
  (documentation snippets) and agent artifacts require independent review after
  commit. Pure non-governed bookkeeping needs no review.

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

## Scope

- Applies to all repositories and all contributors.

## Enforcement

`telec code commit` is the canonical commit interface. The wrapper handles workspace scoping, staging, and pre-commit hooks automatically; direct git operations are blocked and self-document at the error path.

The tool-appended `Co-Authored-By` line and the ambient git author on a commit are
never findings against that commit or the agent that made it. Every commit made
through the surface carries both.

Commit guidance, CLI help, agent addenda, and project-specific designs must not
describe `--approved` as human approval or require a pre-commit human decision.
They may reference this policy and document mechanics, but the commit-first
rule lives here.

## Exceptions

- Emergency production fixes may allow minimal commits with a follow-up cleanup task.
