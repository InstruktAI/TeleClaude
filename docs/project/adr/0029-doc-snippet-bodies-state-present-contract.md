---
adr_status: 'accepted'
date: '2026-06-11'
description: 'A doc-snippet body states present-tense intent and contract only. History belongs in git, rationale in an ADR, pending status and provenance in the delivered_by frontmatter field, and forward design is written as present-tense contract — never as narration in the body. This is enforced by a reviewer lane (doc-snippet hygiene), not an automated grader, because scoring free-text quality in code would violate intelligence-boundaries.'
number: '29'
visibility: 'public'
---

# ADR-0029: Doc-Snippet Bodies State Present-Tense Contract, Caught by a Reviewer Lane — ADR

## Context

Doc snippets had accreted narration: history ("replaces the v1 path", "is retired"), inline rationale ("produced misleading rows"), coordination metadata smeared into body prose ("(delivered*by `<slug>`)", "Pending `<slug>`, the surface is …"), and future framing. `docs/project/spec/telec-cli-surface.md` was the representative sample — nearly every command description carried a `(delivered_by …; authoritative contract: …)` tail and at least one history clause, and two "Planned … surface" sections narrated future work in the body. One of them had been \_delivered*: the planned markers were stripped on delivery and the future-framing prose survived as standing contract.

The doc-first principle already says forward design is first-class and the body describes "the intended shape of the system" — present tense, the design written down. `adr-discipline` already says primary artifacts "MUST describe the current state — they are NOT reasoning logs." So the rule existed in spirit across two snippets, but:

1. It was never named as a concrete authoring anti-pattern about **body prose**.
2. The planned-marker mechanism (`general/procedure/doc-snippet-authoring` §12) documented _how to wrap_ pending content but never stated that the wrapped body must read as present-tense contract — and `strip_planned_markers` (`teleclaude/doc_body.py`) removes only the marker comment lines on delivery, keeping the body verbatim, so a "Pending `<slug>`, …" body becomes a live lie the moment it ships.
3. No review lane inspected snippet **body quality**. The `docs` lane checks that docs exist and reflect the change; the `comments` lane has exactly the right discipline ("the past belongs in git history, not in code") but is scoped to code comments. A snippet full of narration passed every gate.

The narration mechanism spread because the ADD/REPLACE machinery normalized "writing pending/future prose into the live doc is a sanctioned thing." Once future-state narration felt legitimate in the body, the guardrail against _all_ narration was gone, and provenance and history walked in behind it.

## Decision

1. **A doc-snippet body states present-tense intent and contract only.** Each form of narration has a proper home and the body is never it: history → git; rationale → an ADR; pending status and provenance → the `delivered_by` **frontmatter** field; forward design → a present-tense description of the intended shape. A pending snippet's body reads as present-tense contract; `delivered_by` is the only thing that says "not yet". Named as the **Narration (log-in-the-doc)** anti-pattern in `general/policy/snippet-value-contract`.

2. **Planned-block and companion bodies are authored as the future live contract**, verbatim as they must read once delivered. The delivering slug lives only in the planned marker or the companion filename — never in body prose. Stated in `general/procedure/doc-snippet-authoring` §12.

3. **A dedicated `doc-hygiene` review lane** (`software-development/policy/definition-of-done-lanes`) fires whenever the diff touches any `docs/**` snippet and flags the four narration forms in the changed regions, frontmatter, and any newly-added or delivered planned block/companion. It auto-propagates to build-review, commit-review, and plan-review anticipation because those reviewers enumerate the lane catalog dynamically.

4. **The catch is a reviewer lane, not a `telec sync` validator.** `snippet-value-contract` already establishes there is no automated grader for snippet quality — code that judges free-text content semantics violates `general/principle/intelligence-boundaries`. Distinguishing narration from contract is exactly that kind of semantic judgment, so it belongs to the reviewing agent's briefing, not to a regex.

5. **Lane scope is the change, not the whole file.** The lane audits changed regions, frontmatter, and new/delivered planned bodies — never unchanged narration elsewhere in a snippet the diff merely touched. Pre-existing narration is the remediation sweep's job, not an ambush on the next unrelated editor.

## Consequences

- Authors gain one stated rule and reviewers gain one lane; the line ("docs state what is, not how they got here or what is coming") becomes enforceable instead of reviewer-dependent goodwill.
- A one-time remediation sweep is needed to clean existing narration (starting with `telec-cli-surface.md`); it is sequenced _after_ this setup correction lands so the lane exists before the sweep runs.
- A delivered planned/companion body that left future-framing live is a **Critical** finding — the highest severity in the lane — because it is a standing-contract lie, not merely untidy prose.
- A narrow structural guard for the literally-detectable cases (a planned-marker body containing its own slug string) remains possible as a separate, carefully-scoped follow-up; it is deliberately not part of this decision, because the general discipline is a judgment the reviewer owns.

## Alternatives Considered

- **A `telec sync` validator that rejects narration.** Withdrawn: it would judge free-text quality in code, violating `intelligence-boundaries`, and would either over-block (false positives on legitimate present-tense prose) or under-catch (only the few literal patterns).
- **Extend the existing `docs` lane instead of a new lane.** Rejected: the `docs` lane is conditional on CLI/config/API changes, whereas hygiene must fire on _any_ snippet edit. A distinct trigger warrants a distinct lane.
- **Strict whole-file audit on every touched snippet.** Rejected in favor of changed-region scope: re-auditing an entire narrated legacy file because someone fixed one adjacent line punishes the editor for cruft they did not write and creates friction that erodes the rule.
