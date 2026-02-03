---
name: web-research
description: Research topics via web search and scraping using Firecrawl MCP tools. Use when the user asks to explore a technology, gather information on a topic, or scrape web content for analysis. Outputs structured research artifacts under docs/explore/.
---

# Web Research

## Purpose

Perform open-ended web research using Firecrawl MCP tools. Search for information, scrape web pages, and produce structured research artifacts. Covers technology exploration, competitive analysis, architectural research, and any topic the user wants to investigate.

## Scope

- General web research and content scraping via Firecrawl MCP tools.
- Output stored under `docs/explore/` as markdown research artifacts.
- Budget-aware: Firecrawl free tier allows 1000 requests/month. Prefer targeted scrapes over broad crawls.
- Not for stack dependency documentation (use the `stack-docs` skill for that).

## Inputs

- A research brief: topic, question, or URL(s) to investigate.
- Optional: specific websites to prioritize or avoid.

## Outputs

- Markdown research artifact under `docs/explore/{topic-slug}.md` containing findings, key facts, and source URLs.
- If the research yields actionable documentation, it may be promoted to a proper snippet under `docs/third-party/` following the 3rd-party-research procedure.

## Procedure

**Available Firecrawl MCP tools:**

- `mcp__firecrawl-mcp__firecrawl_search` — Search the web for a query. Returns relevant URLs and snippets. Use this for discovery.
- `mcp__firecrawl-mcp__firecrawl_scrape` — Scrape a specific URL and return its content as markdown. Use this for targeted extraction.

**Research workflow:**

1. Clarify the research question. Identify what the user needs to learn.
2. Use `firecrawl_search` to discover relevant pages. Start with the most specific query possible to conserve budget.
3. Review search results. Select the most authoritative and relevant URLs.
4. Use `firecrawl_scrape` on selected URLs to extract full content.
5. Synthesize findings into a structured markdown artifact.
6. Write the artifact to `docs/explore/{topic-slug}.md` with this structure: an H1 title "Research: {Topic}", then **Date**, **Brief** (original question), **Findings** (synthesized key facts organized by subtopic), and **Sources** (list of URLs with brief notes on what was extracted from each).

**Budget management:**

- Each `firecrawl_search` call counts as 1 request.
- Each `firecrawl_scrape` call counts as 1 request.
- Prefer search first, then scrape only the most relevant 2-3 results.
- For large documentation sites, scrape the index/overview page first, then selectively scrape subsections.
- Never crawl an entire site. Target specific pages.

**When to promote to docs/third-party:**

- If the research produces authoritative reference documentation for a technology the project uses, follow the 3rd-party-research procedure to create a proper snippet under `docs/third-party/` and register it in the index.

## Examples

**Explore a new technology:**
User asks: "Research what vector databases exist and how they compare for our use case."

1. `firecrawl_search` with query "vector database comparison 2026 embeddings"
2. Scrape top 2-3 comparison articles
3. Write `docs/explore/vector-database-comparison.md`

**Scrape a specific page:**
User asks: "Get me the content from this blog post: https://example.com/article"

1. `firecrawl_scrape` on the URL
2. Write `docs/explore/example-article.md`

**Deep-dive into an architecture pattern:**
User asks: "Research how other projects implement MCP server resilience."

1. `firecrawl_search` for "MCP server reconnection patterns"
2. Scrape relevant GitHub repos, blog posts, and docs
3. Synthesize into `docs/explore/mcp-resilience-patterns.md`
