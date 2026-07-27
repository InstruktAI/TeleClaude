---
description: Commit attribution names the agent that did the work; the human's identity is lineage, and co-authorship requires a recorded involvement fact.
date: 2026-07-27
number: 71
---

# Agents Author Their Own Commits — ADR

## Context

Every commit in this repository was authored and committed under the human's git identity, with the acting agent recorded only as `Co-Authored-By`. Two further sources reinforced the inversion: each agent addendum instructed its agent to sign with a `Co-Authored-By` trailer, and `telec code commit` appended a standing `Co-Authored-By: TeleClaude` line plus a tool-branding footer to every message.

The result was a history in which the human appeared as the author of work they did not write, agents appeared as assistants on it, and tooling appeared as a contributor. This is the inversion `general/concept/lineage-vs-authorship` exists to prevent: the account the work runs under is lineage, never authorship. Reviewers had already been observed citing commit lineage as evidence of human authorship, drawing false conclusions from the record.

The human directed that the record reflect reality: no co-authorship claim where they were not involved, and clean commit output.

## Decision

Commit attribution names the party that did the work.

- The agent that produced a change is its author and closes the message with an `Agent:` trailer carrying its own identity.
- The human's git identity remains on the commit only as the account the work runs under. It carries no authorship claim.
- `Co-Authored-By: <human>` is emitted **only** when a recorded `human_involved` fact backs that specific change. No record, no trailer.
- Standing co-author lines are prohibited — for the agent, for the human, and for the tooling. Boilerplate attribution asserts involvement that did not occur.
- Commit messages carry no session identifiers. Session provenance is recoverable from the session mirrors; putting internal identifiers in a public, durable history is a repository-privacy cost with no offsetting benefit.

The canonical statement lives in `software-development/policy/commits`; the per-agent identity strings live in each agent's addendum.

## Consequences

The commit record becomes a faithful rendering of who did what, and the human stops being credited with work they did not author.

Two mechanical gaps remain open, and until they close the record is corrected in the message body only: `telec code commit` still writes the human into the git author and committer fields, and still appends the tool co-author trailer that this decision prohibits. Both are tracked as delivery work; the agent-facing instruction is corrected ahead of them so no window opens in which commits carry no agent marker at all.

Attribution correctness now depends on `human_involved` facts being recorded where they are true. An unrecorded involvement produces a commit that under-credits the human — the opposite of the failure being corrected, and the one this decision accepts as the safer error.

## Alternatives Considered

**Keep `Co-Authored-By` for the agent and fix only the author field.** Rejected: the trailer's meaning is "assisted with someone else's work." Retaining it would preserve the inversion in prose while correcting it in metadata, leaving the two halves of the record disagreeing.

**Emit `Co-Authored-By: <human>` on every commit, on the grounds that the work runs under their account.** Rejected by the human directly. It is the boilerplate that created the problem, and it asserts an involvement that is usually false.

**Carry a session identifier for exact provenance.** Rejected on repository-privacy grounds: durable public history is the wrong place for internal identifiers, and the session mirrors already resolve provenance without them.
