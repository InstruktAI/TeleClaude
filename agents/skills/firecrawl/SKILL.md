---
name: firecrawl
description: Last-resort web scraping when built-in web search and consolidated docs are insufficient. Use for JavaScript-rendered SPAs, structured data extraction from pages, multi-page crawling, or when web search cannot access the content.
---

# Firecrawl Web Scraping

## Purpose

Scrape web content that built-in web search cannot reach — JavaScript-rendered SPAs, structured data behind client-side rendering, or multi-page site crawls. Each scrape costs one credit (1000/month free tier), so prefer web search and consolidated docs first.

## Scope

- Single-page scraping to markdown via `firecrawl_scrape`.
- Multi-page async crawling via `firecrawl_crawl` + `firecrawl_check_crawl_status`.
- URL discovery and sitemap mapping via `firecrawl_map`.
- LLM-powered structured data extraction via `firecrawl_extract`.
- Autonomous multi-source research via `firecrawl_agent` + `firecrawl_agent_status`.

Limitations: requires the `firecrawl` MCP server (configured via installer). API key loaded from `~/.teleclaude/.env`. Rate limited to plan allowance (free tier: 1000 scrapes/month).

## Inputs

- **URL**: the target URL to scrape or crawl.
- **Mode** (inferred from intent):
  - **scrape**: single URL to markdown.
  - **crawl**: multi-page site exploration.
  - **map**: discover all URLs on a domain.
  - **extract**: pull structured data matching a schema.
  - **agent**: autonomous research across multiple sources.

## Outputs

- **scrape**: Clean markdown content of the page.
- **crawl**: Collection of pages as markdown, delivered incrementally via status polling.
- **map**: List of discovered URLs.
- **extract**: Structured JSON data matching the provided schema.
- **agent**: Research findings compiled from multiple sources.

## Procedure

1. **Confirm this is the right tool.** Check consolidated third-party docs first, then try built-in web search. Only use Firecrawl when those cannot reach the content (SPA, structured extraction, crawl).
2. **Single page scrape** — use `firecrawl_scrape` with the target URL. Optionally pass `formats` (markdown, html, links, screenshot) and CSS selectors to include/exclude content.
3. **Site crawl** — start with `firecrawl_crawl` (pass root URL, optional `limit`, `maxDepth`, `includePaths`, `excludePaths`). Poll `firecrawl_check_crawl_status` with the returned crawl ID until complete.
4. **URL mapping** — use `firecrawl_map` with the root URL to discover all indexed pages. Optionally pass a `search` term to filter.
5. **Structured extraction** — use `firecrawl_extract` with one or more URLs and a JSON `schema` describing the fields to extract. The LLM parses pages and returns structured data.
6. **Autonomous research** — start with `firecrawl_agent` (describe the objective in `prompt`). Poll `firecrawl_agent_status` with the returned agent ID until complete.
