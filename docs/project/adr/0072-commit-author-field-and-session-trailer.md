---
visibility: internal
number: 0072
date: 2026-07-31
description: The sealed commit surface stamps the agent's GitHub bot identity into the git author field and a Session trailer into the message; the interim Agent trailer is retired and the prior session-id omission is reversed.
---

# Commit Author Field And Session Trailer — ADR

## Context

A prior decision corrected commit attribution from a false human-authored record to
an agent-identified one, but left two mechanical gaps open: `telec code commit`
still wrote the human into the git author and committer fields, and still appended a
tool `Co-Authored-By: TeleClaude` trailer. As an interim correction it recorded the
authoring agent via an `Agent:` message trailer instead — an agent-composed prose
line, not a field the sealed surface stamps — and it rejected carrying a session
identifier in commit messages on repository-privacy grounds, judging that internal
session identifiers had no offsetting benefit in durable public history over what
the session mirrors already resolve.

A later diagnosis of the same defect found the `Agent:` trailer mechanism itself to
be the residual weakness: because it is prose an agent chooses to write rather than
a value the commit surface stamps, it remains exactly as unconditional as the
`Co-Authored-By` line it replaced. The diagnosis also found the authoring identity
is resolved as a durable fact at commit time and dropped at the git boundary rather
than being genuinely unavailable. Separately, the `Session:` line is the revival
handle for that exact commit, and its absence from durable history is judged a
greater cost than the repository-privacy cost of carrying it.

## Decision

The sealed commit surface (`telec code commit`) stamps the dispatching agent's
verified GitHub bot identity into the git `--author` field, mechanically and
unconditionally — never through a message trailer an agent must remember to write.
The git committer field is untouched: it continues to carry the human account
identity, which is lineage — the account the work runs under — never authorship.

The commit message carries a mechanically-stamped `Session: <session id>` trailer,
reversing the prior repository-privacy rejection of session identifiers in public
history: the revival-handle benefit is judged to outweigh that cost.
`Human-Involved:` is always present as a bare boolean, declared per commit by the
agent making it from its own awareness of whether a human was present in that
session. It is deliberately not derived from a todo's recorded `human_involved`
fact: that fact is todo-level audit metadata, and the only commits made where it
could be read are the pre-merge sync and worktree-cleanup commits, which the
squash merge discards before anything reaches durable history. The interim
`Agent:` message trailer is retired: the git author field now carries what it
named. The tool's own `Co-Authored-By: TeleClaude` trailer is also retired, closing
the second mechanical gap the prior decision recorded as open. No `Co-Authored-By`
trailer of any kind remains permitted, for the agent, the human, or the tooling.

## Consequences

Attribution is now carried by the two record types built to carry it: the git
author/committer fields for who wrote the change and under whose account, and the
`Session:` trailer for exact provenance. Neither depends on an agent remembering to
compose a line correctly, closing the residual weakness the interim fix left open.

Durable public history now carries internal session identifiers again, which is a
repository-privacy cost the prior decision explicitly weighed and rejected once
already; this decision accepts that cost by the same authority that raised it, in
exchange for the exact-provenance benefit of a revival handle on every commit.

The per-agent addenda (`agents/*.addendum.md`) continue to instruct the `Agent:`
trailer. That instruction is now stale advice, not a wrong commit: the git author
field is authoritative regardless of what an addendum additionally asks an agent to
write. Per `general/policy/agent-artifact-governance`, addenda are human-authored,
in-context main edits, never routed through a todo — this decision does not itself
change their text.

## Alternatives Considered

**Keep the `Agent:` message trailer as the permanent mechanism, since it already
identifies the correct bot identities.** Rejected: it repeats the prior decision's
own diagnosis of the trailer it replaced — a value an agent must remember to write
is exactly as unconditional as the free-text line before it. The mechanism, not the
identity strings it carried, was the defect.

**Leave session identifiers out of commit messages, per the standing rejection.**
Rejected: the revival-handle value of a `Session:` trailer on every commit outweighs
the repository-privacy cost this decision reintroduces.
