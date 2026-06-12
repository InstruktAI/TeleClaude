---
adr_status: 'accepted'
date: '2026-06-11'
description: 'A doc-only commit that changes a doc snippet is not review-exempt: it requires an independent fast/medium doc-hygiene commit-review on the committed SHA. The authoring agent may never review a snippet it wrote, because it believes its own work is correct. The check is narrow and cheap — the doc-hygiene lane over one or two changed snippets — so enforcing it costs little.'
number: '33'
visibility: 'public'
---

# ADR-0033: Doc-Only Commits Require an Independent Doc-Hygiene Review — ADR

## Context

The doc-hygiene review lane (ADR-0029) catches narration, but it only fires inside a _review_ — build-review, commit-review, or plan-review anticipation. Doc-only changes never reach one. The `documentation-discipline` policy routes them "in-context, immediately" on `main`, and the `telec code commit` Path A/B/C card stated it outright: _"A) Docs/config/state only: Commit with --approved. Review is not required."_ The B/C review gate applied only to functional changes.

The result: every doc-only commit — new snippets, edited contracts, ADRs, the reconciliation constitution, and the narration-sweep commits in this very session — landed on `main` with no review at all. The lane built to catch narration could not see the commits most likely to introduce it.

The tempting fix is self-review: have the authoring agent run the lane on its own diff before approving. It fails on its face. An agent that just authored a snippet believes it authored it correctly; reading its own prose against a checklist it already thinks it satisfied is not review, it is confirmation. The narration that slipped through was authored by agents who would have self-certified it clean.

## Decision

A doc-only commit that changes a doc snippet (`docs/**`) requires an **independent** doc-hygiene commit-review, enforced:

1. **Independent, never self.** The authoring agent may not review a snippet it wrote. After the in-context commit, it dispatches a _separate_ reviewer on the commit SHA via `/next-review-commits`.
2. **Fast or medium agent.** The check is narrow — the doc-hygiene lane over one or two changed snippets, confirming present-tense contract and no narration. It needs little reasoning, so a `--mode fast` (or medium) reviewer is correct and cheap. Cost is not a reason to skip it.
3. **Enforced, not advisory.** The Path A card instructs the dispatch and says to wait for `REVIEW COMPLETE`; `documentation-discipline` makes a missing review a violation.
4. **Still in-context, still not a todo.** The review reads the committed diff; it does not re-author. The live design context that makes doc-only work correct is preserved — the reason doc-only work stays out of the lifecycle is untouched.
5. **Scoped to snippets.** Config/state/README-only commits with no doc snippet need no review.

The mechanism already exists: `/next-review-commits` runs the lane catalog by SHA, and the `doc-hygiene` lane triggers on `docs/**` changes. The only change is removing the Path A exemption and naming the dispatch.

## Consequences

- Doc commits are no longer a blind spot; the narration lane finally sees the commits most likely to carry narration.
- Every doc-only snippet change costs one fast reviewer dispatch. The check is narrow, so the cost is small and bounded — the deliberate trade for closing the hole.
- The fix is process + briefing (card text, policy, this ADR), not code that inspects prose — consistent with `intelligence-boundaries` and ADR-0029. Review is the intelligence; nothing grades free text in code.
- `telec code commit`'s Path A card and the `sealed-commit` spec change together: the card is the operative instruction, the spec is its contract.

## Alternatives Considered

- **Author self-review against the lane.** Rejected — an agent does not catch the narration it just wrote; confirmation, not review.
- **A `telec sync` / commit-time validator that scans snippet prose.** Rejected — it inspects free text to judge it, violating `intelligence-boundaries` (see ADR-0029). The reviewer is an agent, not a regex.
- **Route doc-only commits through the full lifecycle.** Rejected — a fresh worker re-derives the design cold, the exact failure `documentation-discipline` exists to prevent. A post-commit review reads the diff without re-authoring, so it avoids that.
