---
name: web-research
description: Research topics via web sources and structured extraction. Use when the user asks to explore a technology, compare approaches, or gather information on a topic. Outputs structured research artifacts under docs/explore/.
---

# Web Research

## Purpose

Perform exploratory research on a topic and produce a structured artifact under `docs/explore/` that captures findings, sources, and gaps.

## Scope

- Broad, open-ended research across multiple sources.
- Output stored under `docs/explore/` as markdown artifacts.
- Not for official dependency documentation (use the `stack-docs` skill for that).
- Apply the Parallel Work principle when independent research threads can run simultaneously.

## Inputs

- A research brief: topic, question, or URL(s) to investigate.
- Optional: specific sites to prioritize or avoid.

## Outputs

- A markdown artifact at `docs/explore/{topic-slug}.md`.
- The artifact should include **Brief**, **Findings**, **Sources**, and **Gaps/Unknowns** sections.
- If research yields authoritative, reusable documentation for a project dependency, promote it to `docs/third-party/` via the normal docs workflow.

## Procedure

1. **Clarify the brief**
   - Define what decision or outcome the research should support.

2. **Plan the threads**
   - Split into independent sub-questions (e.g., definitions, comparisons, pitfalls).
   - Dispatch parallel work where it reduces latency and improves coverage.

3. **Gather sources**
   - Use appropriate discovery and extraction methods (search, targeted scraping, or curated sources).
   - Prefer authoritative sources; record provenance for every key claim.

4. **Synthesize**
   - Combine findings into a structured summary tied to the brief.
   - Clearly separate confirmed facts from uncertainty.

5. **Record gaps**
   - Explicitly list unanswered questions or weakly supported claims.

6. **Stop condition**
   - Stop when the brief is satisfied and remaining gaps are documented.

## Examples

**Explore a new technology:**
User asks: "Research what vector databases exist and how they compare for our use case."

- Split into market survey, core capabilities, and tradeoffs.
- Gather sources, synthesize comparisons, and list gaps.
- Write `docs/explore/vector-database-comparison.md`.

**Scrape a specific page:**
User asks: "Get me the content from this blog post: https://example.com/article"

- Extract content, summarize key points, and cite the source.
- Write `docs/explore/example-article.md`.

**Deep-dive into an architecture pattern:**
User asks: "Research how other projects implement MCP server resilience."

- Split into reconnection patterns, error handling, and operational strategies.
- Synthesize findings with sources and gaps.
- Write `docs/explore/mcp-resilience-patterns.md`.
