---
date: '2026-06-11'
description: 'A doc-snippet body states present-tense intent and contract only. History belongs in git, rationale in an ADR, pending status and provenance in the delivered_by frontmatter field, and forward design is written as present-tense contract — never as narration in the body. This is enforced by a reviewer lane (doc-snippet hygiene), not an automated grader, because scoring free-text quality in code would violate intelligence-boundaries.'
number: '29'
visibility: 'public'
---

# ADR-0029: Doc-Snippet Bodies State Present-Tense Contract, Caught by a Reviewer Lane — ADR

## Context

Doc snippets had accreted narration: history ("replaces the v1 path"), inline rationale, coordination metadata smeared into body prose, and future framing. The doc-first principle and `adr-discipline` already said primary artifacts describe the current state, but the rule was never named as a concrete body-prose anti-pattern, and no review lane inspected snippet body quality. Worse, the planned-marker mechanism normalized writing pending/future prose into the live doc, and on delivery only the marker comments are stripped — so a "Pending <slug>, …" body becomes a standing lie the moment it ships.

## Decision

1. **A doc-snippet body states present-tense intent and contract only.** Each form of narration has a proper home and the body is never it: history → git; rationale → an ADR; pending status and provenance → the `delivered_by` frontmatter field; forward design → a present-tense description of the intended shape. A pending snippet's body reads as present-tense contract; `delivered_by` is the only thing that says "not yet."
2. **Planned-block and companion bodies are authored as the future live contract**, verbatim as they must read once delivered. The delivering slug lives only in the marker or companion filename — never in body prose.
3. **A dedicated `doc-hygiene` review lane** fires whenever a diff touches any `docs/**` snippet and flags narration in the changed regions, frontmatter, and any new/delivered planned body. It propagates to build-, commit-, and plan-review.
4. **The catch is a reviewer lane, not a `telec sync` validator.** Distinguishing narration from contract is a semantic judgment; code that grades free-text quality violates `intelligence-boundaries`. It belongs to the reviewing agent, not a regex.
5. **Lane scope is the change, not the whole file.** The lane audits changed regions only; pre-existing narration is the remediation sweep's job, not an ambush on the next editor.

## Consequences

- Authors gain one stated rule and reviewers gain one lane; "docs state what is, not how they got here or what is coming" becomes enforceable instead of reviewer goodwill.
- A one-time remediation sweep is needed to clean existing narration, sequenced after this lands so the lane exists first.
- A delivered body that left future-framing live is the lane's highest-severity finding — a standing-contract lie, not merely untidy prose.

## Alternatives Considered

- **A `telec sync` validator that rejects narration.** Withdrawn: it judges free-text quality in code (violating `intelligence-boundaries`) and would over-block or under-catch.
- **Extend the existing `docs` lane.** Rejected: that lane is conditional on CLI/config/API changes, whereas hygiene must fire on _any_ snippet edit.
- **Strict whole-file audit on every touched snippet.** Rejected: re-auditing a narrated legacy file because someone fixed one line punishes the editor for cruft they did not write.
