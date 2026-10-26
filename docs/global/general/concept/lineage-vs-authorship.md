---
description: 'Identity on a record is the authority the work ran under, never who did the work. Attribution questions are answered from creation records and session evidence, not account lineage.'
visibility: 'public'
---

# Lineage vs Authorship — Concept

## What

Every durable record in the platform — a git commit, a todo row, an artifact
write — carries identity: an author field, a lineage principal, a chain-root
email. That identity names the **authority the work ran under**, not the party
that did the work. This is an autonomous system: agents do the work, and the
human's identity threads through the work a human originated as lineage because
the system runs under their account. Work with no human origin — the standing
roles and the sessions they start — carries a system principal as its lineage
root instead, and names that system authority in the same way. A commit
authored under the human's name was almost always written by an agent. A todo
whose lineage root is the human was, more often than not, filed by an agent
operating under that lineage.

Attribution questions — "who created this?", "who wrote that?", "did you do
this?" — are answered from the evidence built for them: a todo's creation
record, session transcripts, artifact `updated_by` trails. Account lineage is
never that evidence.

Lineage scopes an authority and never gates a mechanism. It decides what the
authority it names may reach, such as a person's own resources. It never decides
whether a platform mechanism works: a session under system lineage converses,
links, delivers, commits and dispatches exactly as a session under a human's
lineage does. System-rooted work carrying no human lineage is in its true state,
not missing a value. A mechanism neither refuses, holds nor degrades on that
absence, and never substitutes a person for it.

## Why

Agents repeatedly commit the same misreading: they inspect git history or a
lineage field, find the human's name, and conclude the human authored the work
— then assert it back to the human, who is forced to defend against their own
audit trail. The misreading inverts reality precisely where truth matters
most: in an autonomous system, the human is _involved_ in work agents perform;
the human is not its author, its driver, or its origin by default. Reading
lineage as authorship misattributes agent work to humans, corrupts audits,
and erodes the human's trust in every conclusion the agent draws downstream.
The rule exists so no agent ever again treats an authority thread as a
signature.

A mechanism that reads lineage as a functional input breaks for exactly the
work with no human origin: the standing roles and every session they start. It
breaks only once a human first works inside such a session, long after the
change passed review. Substituting a person instead attributes system work to
someone who never directed it. Both failures come from treating an authority
record as a precondition.

## See Also

- ~/.teleclaude/docs/general/policy/human-involvement-recording.md — which facts carry a human-involvement record, and why the declaration is never derived from lineage.
