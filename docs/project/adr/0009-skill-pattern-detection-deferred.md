---
id: 'project/adr/0009-skill-pattern-detection-deferred'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '9'
date: '2026-05-21'
adr_status: 'accepted'
description: 'Skill pattern detection is deferred. Skills, when they come, will be per-human curation of external libraries (not memory-promotion). The future shape is captured in a design doc; no implementation in v2.'
---
# ADR-0009: Skill Pattern Detection Deferred — ADR

## Context

The v2 architecture originally named three consumers of `agent_runtime.extract-window`: `session-history`, `memory-miner`, and `skill-miner`. The skill-miner was envisioned as an intelligence-driven extractor that would detect repeated patterns of behavior across sessions and codify them as skills via `telec context skills create`.

We considered building it. Three problems emerged:

- **Skills have a personal-vs-shared identity crisis.** A pattern observed in one human's sessions might be theirs alone (personal) or universal (shared). Memory has natural disambiguators (subject = email vs project slug); skills don't.
- **External supply meets demand.** Anthropic's skill library, community libraries, prompt patterns — the world has lots of well-formed skills. Mining our own when external supply exists has questionable marginal value.
- **Context window economics.** Skills loaded into every session compound; per-human loadouts require routing around the agent CLI's account/project/global-only skill mechanism. Real engineering work for incremental efficiency gains.

Meanwhile memory has a clear, closed product loop (friction → project memory → todo → fix → upstream) with concrete value.

## Decision

Skill pattern detection is deferred. The `skill-miner` consumer is removed from v2 architecture docs (transport-rules.md, agent_runtime spec, context-map). The forward-looking design for if/when skills return is captured at `docs/project/design/architecture-v2/skills-personal-curation.md` (type: design, status: target).

If skills return, they will be **per-human curation of vetted external libraries**, NOT memory-promoted internal mining:

1. Operator pulls a trusted external skill library via the existing `git-repo-ingestion` procedure (lands at `~/.teleclaude/git/<host>/<owner>/<repo>/`).
2. A Tier-2 process reads accumulated human-category memory and proposes per-human skill associations.
3. Approved associations live in some persistent store (memory triples, dedicated table — undecided).
4. Session-start hook injects a per-human skill manifest pointing the agent at the relevant skill files on disk.

The skill-pattern-detection data path (tool-call sequences, frequency, co-occurrence) is its own concern with its own data shape, NOT memory triples. Memory is for facts about subjects, not patterns of behavior.

## Consequences

**Positive:**

- v2 scope is smaller and more focused. Memory ships cleanly; skills come later (or never) on their own terms.
- The "personal vs shared" tension is preserved as an open question for the future, not papered over with a forced architectural choice now.
- The memory spec stays clean of skill-flavored concerns (no skill-candidate predicates in vocabularies; no behavioral-pattern carve-outs).
- The forward-looking design doc captures intent without committing to implementation, so future work has a starting point.

**Negative:**

- Three consumers shrinks to two. The `skill-miner` consumer entry in `agent_runtime.extractor_cursors` is removed.
- We lose any signal value the skill-miner might have produced. Acceptable: that value is hypothetical, and the discipline cost of preserving it is real.
- "Deferred" decisions tend to accumulate. If skills don't come back in any form, the design doc itself becomes documentation debt. Mitigation: the design doc's `status: target` + `delivered_by: [skills-personal-curation]` keeps it tagged as not-yet-built; we can deprecate it cleanly if we decide later that skills will never come.

## Alternatives Considered

- **Build skill-miner as planned, alongside memory-miner.** Rejected because of the three problems above.
- **Mine skill candidates as memory triples (with a `skill-candidate` predicate).** Considered. Rejected because skill-pattern detection wants temporal sequences with frequency and context — fundamentally different data shape from triples about subjects. Forcing skill data into the memory schema would either lose structure or pollute the predicate vocabulary.
- **Drop the skills concept entirely; never revisit.** Considered. Rejected because the per-human curation framing (external libraries, not internal mining) has real potential value that we don't want to lose visibility of.